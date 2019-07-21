import sys
import file_handling
import helper
import kd_lockfile
import kd_timers
import kd_diskmemory
from clip import Clip
from frame import Frame
from subject import Subject
from library import Library
from kd_log import Log, LogThread
from settings import Settings
from kd_app_thread import AppThread
import plugins
import traceback
import os


#
# ##### CLASS SETUP
#
helper.setup(annotate_line_colour=(0, 255, 255),
             annotate_grid_colour=(102, 153, 153))
kd_lockfile.setup(lock_file=os.path.join(os.path.dirname(__file__), 'safe_start.lock'))
settings = Settings(os.path.join(os.path.dirname(__file__), 'settings_%s.json' % helper.hostname()))
Clip.setup(time_increment=1000,
           annotate_line_colour=(0, 255, 255),
           mp4box_path=(settings.get['processing']['mp4box_path'] if settings.get['processing']['mp4box_path'] else None),
           video_fullpath_fixed=settings.get['processing']['fixed_fullpath'])

main_threads = {}
main_abort = False

Frame.setup(blur_pixel_width=7,
            absolute_intensity_threshold=40,
            morph_radius=15,
            subject_size_threshold=1500,
            source_size_x=3072,
            source_size_y=1728,
            large_size_x=1024,
            medium_size_x=640,
            small_size_x=160)
Subject.setup(bounds_padding=10,
              annotate_line_colour=(0, 255, 255),
              absolute_intensity_threshold=40,
              min_difference_area_percent=0.05,
              min_difference_area_pixels=1500,
              dilate_pixels=25)


#
# ##### WORK THROUGH PENDING VIDEOS
#
def process_video_error(clip, error_msg, video_metadata, error_detail):
    Log.add_entry('activity_log', 'ERROR - %s %s: %s'
                  % (error_msg, video_metadata['filename_new'], error_detail))
    if settings.get['debug']['move_complete_videos']:
        video_path = file_handling.move_to_done(settings.get['folders']['video_error'],
                                                source_fullpath=video_metadata['source_fullpath'],
                                                file_date='',
                                                filename_new=video_metadata['filename_new'])
        file_handling.remove_with_basename(settings.get['folders']['video_pending'],
                                           video_metadata['sub_folder'],
                                           video_metadata['basename_original'])
        file_handling.remove_empty_folder(settings.get['folders']['video_pending'],
                                          video_metadata['sub_folder'])
    else:
        video_path = video_metadata['source_fullpath']

    # In all cases, remove any fixed versions of the video if they were created
    file_handling.remove_fixed_video(settings.get['processing']['fixed_fullpath'])

    kd_timers.clear_timer('vid')
    Log.add_entry('clip_data',
                  {'basename': video_metadata['basename_new'],
                   'video': video_path,
                   'status': 'ERROR - %s' % error_msg,
                   'timestamp': kd_timers.timestamp()
                   })

    if clip is not None:
        for thread_name in sorted(list(clip.threads), reverse=True):
            clip.threads[thread_name].stop(wait_until_stopped=True)
        print('Stopped all sub-threads within video processing!')
        del clip


def process_video(video_filename):

    kd_timers.start_timer('vid')

    # Save details of the file for easier handling later
    video_metadata = file_handling.get_file_metadata(settings.get['folders']['video_pending'], video_filename)

    # If file has been recently modified, don't process yet (to ensure it's completely uploaded)
    if file_handling.is_recently_modified(video_metadata['source_fullpath']):
        kd_timers.clear_timer('vid')
        return False

    if Log.search_log('clip_data', video_metadata['basename_new'], search_key='basename', match_partial=False):
        kd_timers.clear_timer('vid')
        return False

    Log.add_entry('activity_log', 'Processing %s...' % video_metadata['basename_new'])

    base_time = 0

    frames_required_for = ['SEGMENT', 'OUTPUT']

    # Initialise the Clip and get the first frame
    try:
        clip = Clip(video_fullpath=video_metadata['source_fullpath'], base_frame_time=base_time,
                    frames_required_for=frames_required_for)
    except EOFError:
        # Handle errors if the video file can't be opened, or is corrupt, zero size, etc
        process_video_error(None, 'Unable to process', video_metadata, 'Failed to Initialise!')

    else:
        #
        # PRIMARY VIDEO PROCESSING CODE
        #

        # Start thread which gets all frames, up to a maximum number - breaks at end of clip
        clip.threads['1_frame_getter'] = Clip.FrameGetter(clip=clip,
                                                          max_mem_usage_mb=
                                                          settings.get['processing']['max_mem_usage_mb'],
                                                          required_for=frames_required_for)

        # Setup the Clip's exclude_mask, adding to the mask in the appropriate format
        clip.setup_exclude_mask(mask_exclusions=settings.get['masks'])

        # Start a second thread which works through the frames and creates segments, inc getting activity in frames
        clip.threads['2_create_segments'] = Clip.CreateSegments(clip=clip,
                                                                max_mem_usage_mb=
                                                                settings.get['processing']['max_mem_usage_mb'],
                                                                required_for=['OUTPUT', 'COMPOSITE', 'TRIGGER_ZONE'],
                                                                frames_required_for=['COMPOSITE', 'TRIGGER_ZONE'])

        # Use a third thread to create composites
        clip.threads['3_create_composites'] = Clip.CreateComposites(clip=clip)

        # Another thread to check for trigger zone activity
        clip.threads['4_trigger_zones'] = plugins.TriggerZones(clip=clip,
                                                               trigger_zones=settings.get['trigger_zones'])

        # Add annotation of trigger zones
        helper.annotate_contour(annotate_img=clip.base_frame.get_img('annotated'),
                                contour_points_dict=settings.get['trigger_zones'])

        clip.threads['5_output_frames'] = OutputFrames(clip=clip,
                                                       basename=video_metadata['basename_new'],
                                                       file_date=video_metadata['file_date'])
        # helper.sleep(20)
        clip.threads['6_output_segments'] = OutputSegments(clip=clip,
                                                           basename=video_metadata['basename_new'],
                                                           file_date=video_metadata['file_date'],
                                                           pre_requisites=['COMPOSITE', 'TRIGGER_ZONE'])

        #
        # END OF PRIMARY VIDEO PROCESSING CODE
        #

        kd_timers.clear_elapsed_timer('process_video_watchdog')
        kd_timers.clear_elapsed_timer('process_video_watchdog_timeout')
        while True:
            kd_timers.sleep(0.05)
            any_running_threads = False
            running_threads = ''

            if main_abort:
                process_video_error(None, 'Main Thread Abort!', video_metadata, 'Abort Triggered from Main Thread!')
                return False

            # Check status of each running thread
            for thread_name in sorted(list(clip.threads)):
                try:
                    if clip.threads[thread_name].is_running():
                        any_running_threads = True
                        if len(running_threads):
                            running_threads += ', '
                        running_threads += thread_name
                except BaseException as exc:
                    Log.add_entry('activity_log', 'ERROR - %s' % traceback.format_exc())
                    process_video_error(clip, 'Exception in %s' % thread_name, video_metadata, repr(exc))
                    return False

            if any_running_threads:
                if kd_timers.secs_elapsed_since_last(180, 'process_video_watchdog'):
                    Log.add_entry('activity_log', 'Still processing in: %s' % running_threads)
                if kd_timers.secs_elapsed_since_last(720, 'process_video_watchdog_timeout'):
                    Log.add_entry('activity_log', 'Still processing after 12mins in: %s - stopping!' % running_threads)
                    process_video_error(None, 'Process Video Timeout', video_metadata, 'Timed out after 12mins!')
            else:
                break

        # Tidy up videos / move to the 'done' folder
        if settings.get['debug']['move_complete_videos']:
            video_path = file_handling.move_to_done(settings.get['folders']['video_done'],
                                                    source_fullpath=video_metadata['source_fullpath'],
                                                    file_date=video_metadata['file_date'],
                                                    filename_new=video_metadata['filename_new'])
            file_handling.remove_with_basename(settings.get['folders']['video_pending'],
                                               video_metadata['sub_folder'],
                                               video_metadata['basename_original'])
            file_handling.remove_empty_folder(settings.get['folders']['video_pending'],
                                              video_metadata['sub_folder'])
        else:
            video_path = video_metadata['source_fullpath']

        # In all cases, remove any fixed versions of the video if they were created
        file_handling.remove_fixed_video(settings.get['processing']['fixed_fullpath'])

        Log.add_entry('activity_log', 'Video Total Time: %s' % kd_timers.end_timer('vid'))

        # Add details to log file
        log_segments = []
        for segment in clip.segments:
            log_segments.append({'index': chr(65+segment.index),
                                 'time_begin': segment.start_time,
                                 'time_end': segment.end_time,
                                 'trigger_zones': segment.trigger_zones})

        Log.add_entry('clip_data',
                      {'basename': video_metadata['basename_new'],
                       'video': video_path,
                       'is_night': clip.is_night(),
                       'clip_length': '%ds' % clip.video_duration_secs,
                       'segments': log_segments,
                       'timestamp': kd_timers.timestamp()
                       },
                      wait_until_added=True)

        Log.update_aggregate_log('daily_stats')

        del clip
        return True


#
# ##### VIDEO PROCESSING THREAD
#
class VideoProcessing(AppThread):

    def threaded_function(self, max_videos):
        num_processed = 0
        while True:

            if self.should_abort():
                return

            pending_videos = file_handling.get_pending_video_list(settings.get['folders']['video_pending'])
            if len(pending_videos) >= 1:
                process_video_success = False
                while not process_video_success and len(pending_videos) >= 1:

                    if self.should_abort():
                        return

                    process_video_success = process_video(pending_videos.pop(0))
                    if process_video_success:
                        num_processed += 1
                        if num_processed >= max_videos != -1:
                            Log.add_entry('activity_log', 'Max number of videos threshold reached - stopping!')
                        break
                else:
                    kd_timers.sleep(secs=5)
            else:
                kd_timers.sleep(secs=5)


#
# ##### OUTPUT THREADS
#
class OutputFrames(AppThread):

    def threaded_function(self, clip, basename, file_date):

        # One-off - if needed, save an annotated image with grid-lines, masks, etc
        if settings.get['debug']['save_annotated']:
            helper.annotate_grid(annotate_img=clip.base_frame.get_img('annotated'),
                                 spacing=50)
            helper.annotate_contour(annotate_img=clip.base_frame.get_img('annotated'),
                                    contours=clip.retain_mask_contours)
            file_handling.save_image(image=clip.base_frame.get_img('annotated'),
                                     path=settings.get['folders']['images_debug'],
                                     basename=basename,
                                     descriptor='Annotated',
                                     date_subfolder=file_date)

        while True:

            if self.should_abort():
                return

            activity_in_loop = False

            if clip.frames:
                for frame_time in [time for time in list(clip.frames) if clip.frames[time].is_required_for('OUTPUT')]:

                    if self.should_abort():
                        return

                    # If needed, save individual crops of every subject
                    if settings.get['debug']['save_subject_crops']:

                        # If we haven't yet tested for subjects and activity, break out of the for loop for now, and let
                        #  the while loop kick-in to try again
                        if not (clip.frames[frame_time]._tested_subjects
                                and clip.frames[frame_time]._tested_subject_activity):
                            break

                        activity_in_loop = True
                        subject_num = 0
                        for subject in clip.frames[frame_time].subjects:

                            if self.should_abort():
                                return

                            if subject.is_active:

                                img_crop = subject.get_cropped_img(clip.frames[frame_time].get_img('large'),
                                                                   annotate=False)
                                file_handling.save_image(image=img_crop,
                                                         path=settings.get['folders']['images_debug'],
                                                         basename=basename,
                                                         descriptor='SubjectCrop%d%s' % (frame_time,
                                                                                         chr(97 + subject_num)),
                                                         date_subfolder=file_date)
                                subject_num += 1

                    # If needed, save entire frames
                    if (settings.get['debug']['save_frames_all'] or
                            settings.get['debug']['save_frames_with_subjects'] or
                            settings.get['debug']['save_frames_active']):

                        # Use num_active to determine whether to save this frame, depending on the debug options
                        #  chosen.  If saving all, then just set it true, otherwise get the number of subjects
                        #  (active or not) to determine whether the frame is needed.
                        if settings.get['debug']['save_frames_all']:
                            num_active = True
                        elif settings.get['debug']['save_frames_with_subjects']:
                            num_active = clip.frames[frame_time].num_subjects(only_active=False)
                        else:
                            num_active = clip.frames[frame_time].num_subjects(only_active=True)

                        activity_in_loop = True
                        if num_active:
                            file_handling.save_image(image=clip.frames[frame_time].get_img('large'),
                                                     path=settings.get['folders']['images_debug'],
                                                     basename=basename,
                                                     descriptor='Frame%d' % frame_time,
                                                     date_subfolder=file_date)

                    # Once we've processed the frame, without breaking out, remove its OUTPUT requirement so it can
                    #  then be cleared from memory.
                    clip.remove_redundant_frame(frame_time, ['OUTPUT'])

            # Drop out of the while loop if we've retrieved all the frames AND there are no more valid frames pending
            if clip.retrieved_all_frames and not clip.frames_required(required_for='OUTPUT'):
                break

            # If there was no activity, pause slightly to allow other threads to catch up before trying again
            if not activity_in_loop:
                kd_timers.sleep(0.1)


class OutputSegments(AppThread):

    def threaded_function(self, clip, basename, file_date, pre_requisites):

        while True:

            if self.should_abort():
                return

            activity_in_loop = False

            if clip.segments and clip.segments_required(required_for='OUTPUT'):

                # Save each composite from each segment
                for segment in [segment for segment in clip.segments if segment.is_required_for('OUTPUT')
                                and not segment.is_required_for(pre_requisites, bool_and=False)]:

                    # print('Seg Req For %s' % segment.required_for)
                    # print('Len Composites %d' % len(segment.composites))

                    activity_in_loop = True

                    # print('Clip Num Segments %d' % clip.num_segments)

                    if clip.num_segments == 1:
                        segment_basename = basename
                    else:
                        segment_basename = '%s%s' % (basename, chr(65+segment.index))

                    # print('Clip Seg Index %d' % segment.index)

                    # If this is a second segment, append A to the basename of the first
                    if segment.index == 1:
                        file_handling.rename_basename_append(settings.get['folders']['images_output'], file_date,
                                                             basename, 'A', conditional_suffix='Composite')
                        file_handling.rename_basename_append(settings.get['folders']['images_debug'], file_date,
                                                             basename, 'A', conditional_suffix='Composite')

                    # TODO: Make this more flexible / generic - move this functionality elsewhere!
                    # TODO: Should also take account of e.g. people in image, movement tracks, etc...
                    group_subfolder = None
                    for trigger_zone in segment.trigger_zones:
                        if group_subfolder:
                            group_subfolder += '+' + trigger_zone
                        else:
                            group_subfolder = trigger_zone

                    for composite in segment.composites:

                        # print('Style: %s' % composite['style'])

                        if composite['style'] in settings.get['outputs']['composite_styles']:
                            file_handling.save_image(image=composite['composite'],
                                                     path=settings.get['folders']['images_output'],
                                                     basename=segment_basename,
                                                     descriptor='Composite-%s' % composite['style'],
                                                     date_subfolder=file_date,
                                                     group_subfolder=group_subfolder)
                        elif composite['style'] in settings.get['debug']['composite_styles']:
                            file_handling.save_image(image=composite['composite'],
                                                     path=settings.get['folders']['images_debug'],
                                                     basename=segment_basename,
                                                     descriptor='Composite-%s' % composite['style'],
                                                     date_subfolder=file_date,
                                                     group_subfolder=group_subfolder)

                    # print('Removing Output Req')
                    segment.remove_requirement('OUTPUT')

            # print('Created All Segments: %s' % clip.created_all_segments)
            # print('Segments Req for Output: %s' % clip.segments_required(required_for='OUTPUT'))

            # Drop out of the while loop if we've retrieved all the frames AND there are no more valid frames pending
            if clip.created_all_segments and not clip.segments_required(required_for='OUTPUT'):
                break

            # If there was no activity, pause slightly to allow other threads to catch up before trying again
            if not activity_in_loop:
                kd_timers.sleep(0.1)


#
# ##### SYS STATUS THREAD
#
class SysStatus(AppThread):

    def threaded_function(self, every_x_secs):
        first_run = True
        while True:
            if self.should_abort():
                return

            # Add memory usage to the log file every 10mins
            if kd_timers.secs_elapsed_since_last(secs=every_x_secs, timer_id='mem_usage') or first_run:
                first_run = False
                kd_diskmemory.clear_memory()
                Log.add_entry('activity_log', 'Sys Mem Free: %dMB, KDCam Mem Usage: %dMB, Temp: %s' %
                              (kd_diskmemory.memory_free(), kd_diskmemory.memory_usage(), helper.get_temp_str()))
            else:
                kd_timers.sleep(secs=1)


#
# ##### CLEANUP THREAD
#
class Cleanup(AppThread):

    def threaded_function(self):
        first_run = True
        while True:

            if self.should_abort():
                return

            space_critical, _ = kd_diskmemory.is_disk_space_low(settings.get['folders']['video_done'],
                                                                settings.get['disk_space']['critical_remaining_gb'])
            if space_critical:
                # TODO: Remove something that's really quick to remove here!  Suggests major error, so data loss is ok!
                pass

            space_low, free_space = kd_diskmemory.is_disk_space_low(settings.get['folders']['video_done'],
                                                                    settings.get['disk_space']['min_remaining_gb'])
            if (kd_timers.secs_elapsed_since_last(secs=settings.get['disk_space']['check_interval_secs'],
                                               timer_id='diskspace')
                    or free_space < settings.get['disk_space']['critical_remaining_gb']
                    or first_run):
                first_run = False

                Log.add_entry('activity_log', 'Disk free space: %.1fGB' % free_space)
                if space_low or settings.get['debug']['always_cleanup']:
                    folder_info = [(f, settings.get['folders'][f]) for f in
                                   ['video_done', 'images_output', 'images_debug']]
                    Log.add_entry('activity_log', '  Building Library...')
                    library = Library(folder_info)
                    Log.add_entry('activity_log', '  Determining Cleanup Folder...')
                    library.determine_cleanup_folder(settings.get['disk_space']['target_ratios'])
                    Log.add_entry('activity_log', '  Getting File Ages...')
                    library.get_file_ages()
                    Log.add_entry('activity_log', '  Modifying File Ages...')
                    library.modify_ages(Log.get_entire_log('clip_data'))

                    Log.add_entry('activity_log', '  Removing Files...')
                    library.do_cleanup(min_gb_to_remove=settings.get['disk_space']['min_gb_to_remove'],
                                       min_remaining_gb=settings.get['disk_space']['min_remaining_gb'],
                                       gb_free_space=free_space)
                    for file in library.deleted_files:
                        Log.add_entry('activity_log',
                                      '  Deleted file (%s): %s' % (library.cleanup_folder, file['basename']))
                    for folder in library.deleted_folders:
                        Log.add_entry('activity_log', '  Deleted folder (%s): %s' % (library.cleanup_folder, folder))

                    Log.add_entry('activity_log', '  Cleaning Up Log Entries...')
                    basenames_set, basenames_list = library.basenames_setlist()
                    # Note that by using basenames_set, we will always delete anything from Log that doesn't match
                    # the standard filename format!  But could expand regex in Library to return more valid basenames...
                    deleted_log_entries = Log.cleanup_log('clip_data', basenames_set, 'basename')
                    for entry in deleted_log_entries:
                        Log.add_entry('activity_log', '  Deleted log entry: %s' % entry)

                    Log.add_entry('activity_log', '  Cleanup Complete!')

                Log.cleanup_log_by_date('activity_log', num_days_to_keep=7)
            else:
                kd_timers.sleep(5)

    def __init__(self, wait_for_critical, **kwargs):
        super().__init__(**kwargs)

        # Prevent the rest of the application from continuing if disk space is below the critical threshold
        if wait_for_critical:
            while True:

                if self.should_abort():
                    return

                space_critical, _ = kd_diskmemory.is_disk_space_low(settings.get['folders']['video_done'],
                                                                    settings.get['disk_space']['critical_remaining_gb'])
                if not space_critical:
                    break
                else:
                    Log.add_entry('activity_log', 'Disk space critical on startup - waiting for cleanup...')
                    kd_timers.sleep(secs=120)


#
# ##### MAIN PROGRAM LOOP
#
def main():
    global main_threads
    #

    # Generate Log in separate thread
    Log('clip_data', settings.get['files']['clip_data'], simple=False)
    Log('activity_log', settings.get['files']['activity_log'], simple=True, print_also=True)
    Log.define_aggregate('daily_stats', settings.get['files']['daily_stats'],
                         [
                             {'name': 'num_clips_all', 'source': 'clip_data',
                              'function': lambda log_data: len(log_data)},
                             {'name': 'num_clips_all_inactive', 'source': 'clip_data',
                              'function': lambda log_data: len([d for d in log_data if not d.get('segments')])},
                             {'name': 'num_segments_all', 'source': 'clip_data',
                              'function': lambda log_data: sum([len(d.get('segments', [])) for d in log_data])},
                             {'name': 'total_clip_length', 'source': 'clip_data',
                              'function': lambda log_data: kd_timers.secs_to_hhmmss(
                                  sum([int(d.get('clip_length', '0s')[:-1]) for d in log_data]))},
                             {'name': 'num_clips_day', 'source': 'clip_data',
                              'function': lambda log_data: len([d for d in log_data if not d.get('is_night')])},
                             {'name': 'num_clips_day_inactive', 'source': 'clip_data',
                              'function': lambda log_data: len([d for d in log_data if not d.get('is_night')
                                                                and not d.get('segments')])},
                             {'name': 'num_segments_day', 'source': 'clip_data',
                              'function': lambda log_data: sum([len(d.get('segments', [])) for d in log_data
                                                                if not d.get('is_night')])},
                             {'name': 'num_clips_night', 'source': 'clip_data',
                              'function': lambda log_data: len([d for d in log_data if d.get('is_night')])},
                             {'name': 'num_clips_night_inactive', 'source': 'clip_data',
                              'function': lambda log_data: len([d for d in log_data if d.get('is_night')
                                                                and not d.get('segments')])},
                             {'name': 'num_segments_night', 'source': 'clip_data',
                              'function': lambda log_data: sum([len(d.get('segments', [])) for d in log_data
                                                                if d.get('is_night')])},
                             {'name': 'num_app_restarts', 'source': 'activity_log',
                              'function': lambda log_data: len([d for d in log_data
                                                                if d[29:] == '*** Started KDCam Application! ***'])},
                             {'name': 'total_processing_time', 'source': 'activity_log',
                              'function': lambda log_data: kd_timers.secs_to_hhmmss(sum([float(d[47:-1]) for d in log_data
                                                                                 if d[29:46] == 'Video Total Time:']))}
                         ])

    # Startup other threads: for logging, disk cleanup, and regularly logging system status
    main_threads['1_log'] = LogThread()
    Log.add_entry('activity_log', '*** Started KDCam Application! ***')
    main_threads['2_cleanup'] = Cleanup(wait_for_critical=True)
    main_threads['3_sys_status'] = SysStatus(every_x_secs=1800)
    if not settings.get['debug']['skip_videos']:
        main_threads['4_video_processing'] = VideoProcessing(max_videos=settings.get['debug']['max_videos'])

    # If debugging and want to quit early, stop things safely
    if settings.get['debug']['run_once']:
        for thread_name in sorted(list(main_threads), reverse=True):
            main_threads[thread_name].stop(wait_until_stopped=True)
        print('Stopped all main threads!')
        kd_lockfile.remove_safe_lock()

    # Everything is running in threads... just have this as a placeholder for now to keep things running
    while True:
        kd_timers.sleep(5)
        any_running_threads = False
        running_threads = ''

        # Check status of each running thread
        for thread_name in sorted(list(main_threads)):
            try:
                if main_threads[thread_name].is_running():
                    any_running_threads = True
                    if len(running_threads):
                        running_threads += ', '
                    running_threads += thread_name
            except BaseException as exc:
                Log.add_entry('activity_log', 'ERROR - %s' % traceback.format_exc())
                Log.add_entry('activity_log', 'ERROR - Exception in %s: %s'
                              % (thread_name, repr(exc)))
                return False

        if any_running_threads:
            if kd_timers.secs_elapsed_since_last(3600, 'main_watchdog'):
                Log.add_entry('activity_log', 'Active threads: %s' % running_threads)
        else:
            break


    #

    # doc = dominate.document(title='ZZCam')
    # with doc:
    #     p('testing...')
    #
    # with open('test.htm', 'w') as doc_handle:
    #     try:
    #         doc_handle.write(doc.render())
    #     except OSError:
    #         # If e.g. disk full or unable to write, continue running anyway...
    #         pass

#


#
# ##### ENTRY POINT
#
if __name__ == "__main__":

    # Check if it is safe to start, i.e. only run if not already (or very recently) running
    if len(sys.argv) >= 2 and sys.argv[1] == 'safe_start':
        if kd_lockfile.check_safe_lock(150):
            print('Script already running - exiting!')
            exit()

    kd_lockfile.start_safe_lock_async(60)

    # Handle ctrl+c / stop debug commands by safely stopping all threads
    try:
        main()
    except KeyboardInterrupt:
        print('Request to Terminate the Application - Stopping Gracefully...')
        pass
    finally:
        for thread_name in sorted(list(main_threads), reverse=True):
            main_threads[thread_name].stop(wait_until_stopped=True)
        kd_lockfile.remove_safe_lock()
        print('Safely Stopped the Application!')
        sys.exit()
