import cv2
import numpy
import random
import helper
from frame import Frame
from app_thread import AppThread


class Clip:
    """ The Clip class represents a single, entire video file, and acts as parent for Frames, Subjects, etc.

        The class loads the video from a source provided during init, and gets the first frame as the base_frame.
        It is also able to calculate and store a range of clip-level parameters, e.g. whether it's daytime/night,
        a mask of any areas to ignore across the entire length of the clip, etc.
        Clip is also responsible for creating composites images, representing the entire clip within a static image
        (or a small number of images) - various approaches are used depending on the type of activity in the Clip.
        Clip is dependent on Frame (and indirectly on Subject), as a project-specific dependency.
    """

    #
    # ##### CLASS ATTRIBUTES
    #
    _is_setup = False
    _time_increment_default = False
    _annotate_line_colour = None
    _required_for = []

    # findContours returns (image, contours, hierarchy) in OpenCV 3, but (contours, hierarchy) in OpenCV 2 and OpenCV 4
    _contours_return_index = 1 if cv2.__version__.startswith('3.') else 0

    #
    # ##### SETUP METHODS
    #
    @staticmethod
    def setup(time_increment, annotate_line_colour):
        """ Clip.setup() must be called prior to creating a Clip instance.
            Typically this would be at the top of the main file.  Clip.setup() in turn calls
            Frame.setup_time_increment to pass on that parameter - just to save passing multiple times elsewhere.
            :param time_increment: This is the time, in milliseconds, between subsequent frames.
            :param annotate_line_colour: A tuple in BGR format i.e. (b, g, r), with each value 0-255, for annotations
        """
        Clip._is_setup = True
        Clip._time_increment_default = time_increment
        Clip._annotate_line_colour = annotate_line_colour
        # Pass on the time_increment, for neater code / to make it more readily available within multiple Frame methods
        Frame.setup_time_increment(time_increment)

    #
    # ##### INIT METHODS
    #
    def __init__(self, video_fullpath, base_frame_time, frames_required_for, time_increment=-1):
        """ Create a new instance of a Clip.  Should be passed a fully-qualified path to the video file, and the time
            in milliseconds at which the base_frame should be set (usually 0).
            :param video_fullpath: A fully qualified path to a video file (which can be loaded by cv2.VideoCapture).
            :param base_frame_time: The time at which to take the first (base) frame, in milliseconds.
            :param time_increment: TODO: Documentation!
        """

        # Check here that Clip class properties are set
        if not Clip._is_setup:
            raise Exception('Must call Clip.setup() before creating a Clip instance')

        # Create an empty dictionary to store this clip's frames - dictionary key will be time in milliseconds, and
        #  the dictionary value is a Frame object
        self.frames = {}
        self.retrieved_all_frames = False
        # Create an empty list to store this clip's composites
        self.composites = []
        self.segments = []
        self.num_segments = 0
        # self.active_segments = 0
        self.created_all_segments = False

        # Set the time_increment - using either a default or custom specified value
        if time_increment > 0:
            self.time_increment = time_increment
        else:
            self.time_increment = Clip._time_increment_default
        # Re-set the Frame time_increment, to ensure it matches that for the Clip
        Frame.setup_time_increment(self.time_increment)

        # Load the video stream, and get the first frame - saved to both frames[base_frame_time] and base_frame, for
        #  more convenient accessibility
        self._video_capture = cv2.VideoCapture(video_fullpath)
        if not self._video_capture.isOpened():
            # Handle any error opening the video as EOF, as that is handled as all errors and will skip this clip.
            raise EOFError
        self._frames_per_second = self._video_capture.get(cv2.CAP_PROP_FPS)
        self._frame_count = self._video_capture.get(cv2.CAP_PROP_FRAME_COUNT)

        if self._frame_count == 0:
            raise EOFError

        self.video_duration_secs = self._frame_count / self._frames_per_second
        self.frames[base_frame_time] = Frame.init_from_video_sequential(self._video_capture, base_frame_time,
                                                                        frames_required_for)
        self.base_frame = self.frames[base_frame_time]
        # Create an empty _retain_mask.  Note that this mask is used to exclude areas of the
        #  frame from processing, but masks are used such that non-zero values mark the areas we want to keep, i.e.
        #  anything non-zero will be retained.  The default therefore is that the entire frame is 255 values by
        #  default, and any areas to exclude will be added by setting those values to zero.
        #  A variety of methods within Clip are used to modify this mask, i.e. to mark areas to exclude.
        # retain_mask_contours stores an array of contours, reflecting everything added to the mask
        self._retain_mask = numpy.ones(self.base_frame.dimensions_numpy.large, numpy.uint8) * 255
        self.retain_mask_contours = []

        # Keep track of clip-level properties for easy access
        self._is_night = None

        # Thread placeholders
        self.threads = {}


    def remove_redundant_frame(self, time, expired_requirement=None):
        """
            TODO: Add documentation
            :param time:
            :param expired_requirement:
            :return:
        """
        if time not in self.frames:
            print('Attempt to remove requirement non-existing frame %d' % time)
            return
        # print(self.frames[time].required_for, end='')
        if expired_requirement:
            self.frames[time].remove_requirement(expired_requirement)
        # print(self.frames[time].required_for)
        if not self.frames[time].is_required() and not time == self.base_frame.time:
            # print('   Redundant frame %d... deleted!' % time)
            del self.frames[time]

    def remove_redundant_frames_before(self, time, expired_requirement=None):
        """
            TODO: Add documentation
            :param time:
            :param expired_requirement:
            :return:
        """
        # print('Removing redundant frames before %d' % time)
        for this_time in [this_time for this_time in list(self.frames) if this_time < time]:
            self.remove_redundant_frame(this_time, expired_requirement)

    def replace_base_frame(self, new_time):
        # print('Removing frame as base frame at %d' % self.base_frame.time)
        # self.remove_redundant_frame(self.base_frame.time, 'BASE_FRAME')
        # self.frames[new_time].add_requirement('BASE_FRAME')
        self.base_frame = self.frames[new_time]

    def remove_base_frame(self):
        self.remove_redundant_frame(self.base_frame.time, 'BASE_FRAME')
        self.base_frame = None

    def segments_required(self, required_for=None):
        for segment in self.segments:
            if required_for is None:
                if segment.is_required():
                    return True
            elif segment.is_required_for(required_for):
                return True
        return False

    def frames_required(self, required_for=None):
        for frame_time in self.frames:  # Frames is a dict - for loop uses the key (time)
            if required_for is None:
                if self.frames[frame_time].is_required():
                    return True
            elif self.frames[frame_time].is_required_for(required_for):
                return True
        return False


    #
    # FRAME GETTER THREAD
    #
    class FrameGetter(AppThread):

        def threaded_function(self, clip, max_mem_usage_mb, required_for):
            time = clip.base_frame.time
            while time <= clip.video_duration_secs * 1000:

                if self.should_abort():
                    return

                if helper.memory_usage() > max_mem_usage_mb:
                    helper.sleep(0.25)
                    continue

                if time not in clip.frames:
                    try:
                        clip.frames[time] = Frame.init_from_video_sequential(clip._video_capture, time, required_for)
                    except EOFError:
                        # An alternative way to break out of the while loop, in case video ends prematurely
                        break
                time += clip.time_increment

            # If we get to the end, means we've got all frames - any errors use 'return' so won't get here
            clip.retrieved_all_frames = True


    #
    # CREATE SEGMENT THREAD
    #
    class CreateSegments(AppThread):

        def threaded_function(self, clip, max_mem_usage_mb, required_for, frames_required_for):
            segment_start_time = 0
            mem_low = False

            # Outer while loop ensures we get all segments
            while True:

                if self.should_abort():
                    return

                frames_in_segments = []
                final_segment = False
                frame_was_processed = False
                frame1_time = segment_start_time

                # Inner while loop ensures we get all the frames for each segment
                while True:

                    if self.should_abort():
                        return

                    # Increment the frame time, after it has been successfully processed
                    if frame_was_processed:

                        # Before we move on, check that frame1_time is in a segment, otherwise remove its requirement
                        if frame1_time not in frames_in_segments and frame1_time < segment_start_time:
                            clip.remove_redundant_frame(frame1_time, 'SEGMENT')

                        frame1_time += clip.time_increment
                        frame_was_processed = False

                    # Frame2 always follows frame1
                    frame2_time = frame1_time + clip.time_increment

                    # If Python exceeds memory limit, finish segment early
                    if helper.memory_usage() > max_mem_usage_mb:
                        mem_low = True
                        print('  EXCESS MEMORY USAGE: %.1fMB' % helper.memory_usage())
                        segment_end_time = frame1_time  # end_time is frame1, as we haven't processed frame2 yet
                        break

                    if frame1_time in clip.frames and frame2_time in clip.frames:
                        clip.frames[frame2_time].get_subjects_and_activity(clip.base_frame, clip.frames[frame1_time],
                                                                           clip._retain_mask)
                        if clip.frames[frame2_time].num_subjects() == 0:
                            if frame1_time == clip.base_frame.time:
                                # If no subjects, and follows the base_frame, then make this the new base frame
                                clip.replace_base_frame(frame2_time)
                                segment_start_time = frame2_time
                            else:
                                # If no subjects, indicate end of this segment by returning the time we got to
                                segment_end_time = frame2_time  # end_time is frame2 - has been processed and not needed
                                break
                        frame_was_processed = True

                    elif clip.retrieved_all_frames:
                        segment_end_time = frame1_time  # end_time is frame1 - gone beyond the end of the frame list
                        final_segment = True
                        break

                    else:
                        # If frame not yet available, wait for a short time before trying again
                        helper.sleep(0.05)

                if self.should_abort():
                    return

                # When we've got the frames for each segment, save the details as a finished segment
                if segment_end_time > segment_start_time:
                    # print('Creating segment index %d' % clip.num_segments)
                    this_segment = Segment(clip.num_segments, segment_start_time, segment_end_time, required_for)
                    frames_in_segments.extend(range(segment_start_time, segment_end_time, clip.time_increment))
                    clip.segments.append(this_segment)
                    clip.num_segments += 1
                    # Also mark the frames within this segment with their new requirements, then remove the SEGMENT req
                    for frame_time in range(segment_start_time, segment_end_time, clip.time_increment):
                        clip.frames[frame_time].add_requirement(frames_required_for)
                        clip.frames[frame_time].remove_requirement('SEGMENT')

                if final_segment:
                    # clip.remove_base_frame_requirement()  # Do this after composite later...
                    break
                else:
                    clip.replace_base_frame(segment_end_time)
                    segment_start_time = segment_end_time

                if mem_low:
                    helper.sleep(0.5)

            # If we make it to the end, means we have created all segments - errors will 'return' instead
            # print('End of Get Segments, len(clip.segments) = %d' % len(clip.segments))
            if len(clip.segments) > 0:
                # print('Segment %d (starting %d) is last_segment' % (clip.segments[-1].index, clip.segments[-1].start_time))
                clip.segments[-1].last_segment = True
            clip.created_all_segments = True


    #
    # CREATE COMPOSITES THREAD
    #
    class CreateComposites(AppThread):

        def threaded_function(self, clip):
            segment_index = 0
            while True:

                if self.should_abort():
                    return

                segment = None
                for seg in clip.segments:
                    if seg.index == segment_index:
                        segment = seg
                        break

                if segment is not None:
                # for segment in [seg for seg in clip.segments if seg.index == segment_index]:

                    # print('Creating Composites for segment %d (starting %d)' % (segment.index, segment.start_time))

                    # Generate a single composite encompassing all activity, overlapping subjects if necessary
                    clip.get_complete_composite(segment=segment,
                                                style='Complete')

                    # Generate a primary composite, which includes the largest subject nearest the centre of the frame,
                    # plus any other non-overlapping subjects which fit
                    center_frame = [pt / 2 for pt in clip.base_frame.dimensions.large]
                    clip.get_composite_primary(segment=segment,
                                               target_point=center_frame,
                                               min_fraction_of_max_area=0.75,
                                               inc_fallback=True)

                    # Generate non-overlapping composites covering all remaining subjects
                    while True:
                        try:
                            clip.get_composite_fallback(segment=segment)
                        except EOFError:
                            break

                    # Remove required_for flag on frames so far
                    clip.remove_redundant_frames_before(segment.end_time, 'COMPOSITE')
                    # clip.remove_redundant_frame(segment.end_time, 'COMPOSITE')              # MOVED FROM BELOW...
                    segment.remove_requirement('COMPOSITE')
                    # print('Removed Seg %d requirement for COMPOSITE' % segment.index)

                    # if segment.last_segment:
                    #     print('Composite - reached last segment, about to break!')
                    #     clip.remove_redundant_frame(segment.end_time, 'COMPOSITE')
                    #     # break
                    # else:
                    segment_index += 1

                else:
                    if clip.created_all_segments:
                        # clip.remove_redundant_frames_before(max(list(clip.frames)) + 1, 'COMPOSITE')
                        break
                    helper.sleep(secs=0.05)


    #
    # ##### WHOLE CLIP CHARACTERISTIC METHODS
    #
    def is_night(self):
        """ Test whether the frame is daytime (full colour) or night-time (greyscale, but still encoded as BGR).
            Greyscale is detected by each of the R, G and B components being equal to each other.  Randomly test
            a few, just to ensure we're not skewed by a genuinely grey object in the daytime (colour) image.
            If already tested, then will retrieve that value rather than re-calculate.
            :return: Returns boolean true if it is a night-time image.
        """
        if self._is_night is None:
            # Test the original source image
            test_img = self.base_frame.get_img('source')
            for _ in range(25):
                x = random.randint(0, test_img.shape[1] - 1)
                y = random.randint(0, test_img.shape[0] - 1)
                if test_img[y, x, 0] == test_img[y, x, 1] and test_img[y, x, 1] == test_img[y, x, 2]:
                    # If this is greyscale, keep testing in case it's a genuinely grey object in a colour image
                    continue
                else:
                    # As soon as we find a single colour pixel, we know the image is colour so stop checking
                    self._is_night = False
                    break
            else:
                # It's only night-time if we've found no reason to break out of the loop, i.e. found no colour pixels
                self._is_night = True
        return self._is_night

    #
    # ##### MASK HANDLING METHODS
    #
    def setup_exclude_mask(self, mask_exclusions):
        # Setup the Clip's exclude_mask, adding to the mask in the appropriate format
        for mask_exclusion in mask_exclusions:
            if mask_exclusion['type'] == 'contour' and isinstance(mask_exclusion['value'], list):
                self.exclude_contour_from_mask(mask_exclusion['value'])
            elif mask_exclusion['type'] == 'image' and isinstance(mask_exclusion['value'], str):
                self.exclude_img_from_mask(mask_exclusion['value'])
            else:
                raise Exception('Invalid mask_exclusion type')


    def exclude_contour_from_mask(self, contour_points, annotate_img=None):
        """ Marks an area to exclude from the _retain_mask, i.e. an area to be ignored when detecting movement.
            The area should be enclosed within a contour, in simple python list format [[x,y],[x,y],[x,y]] - this will
            be converted to a numpy array within this method.  The contour will be closed automatically, i.e. there
            is no need to repeat the first point as the final point.
            An optional annotate_img argument can be passed, onto which the contour outline will be plotted - this is
            primarily intended for debugging / understanding how the image processing is working.
            Any updates are carried out in-place - there is no return value from this method.
            :param contour_points: A simple python list, in the format [[x,y],[x,y],[x,y],...]
            :param annotate_img: A 'large' sized image onto which the contour will (optionally) be plotted - or None.
        """
        contour = numpy.array(contour_points, dtype=numpy.int32)
        cv2.drawContours(self._retain_mask, [contour], -1, (0, 0, 0), cv2.FILLED)
        # Add this contour to the record of contours added to the mask - as it's a single contour, append it
        self.retain_mask_contours.append(contour)
        if annotate_img is not None:
            cv2.drawContours(annotate_img, [contour], -1, Clip._annotate_line_colour, 1)

    def exclude_img_from_mask(self, mask_path, annotate_img=None):
        """ Marks an area to exclude from the _retain_mask, i.e. an area to be ignored when detecting movement.
            The area to exclude is defined by passing a path to an image of a mask, which (as with all retain_masks
            in this application) will have objects coloured black (0) on a white (255) background.  This allows an easy
            bitwise_and operation to exclude any masked (black) areas.
            However, within this function we need to invert the mask in order to find the contours.  This is because
            the OpenCV findContours function will only find white objects on a black background.  Despite the apparent
            invert, the final mask still consists of black objects / areas to exclude on a white background.
            An optional annotate_img argument can be passed, onto which the object outline will be plotted - this is
            primarily intended for debugging / understanding how the image processing is working.
            Any updates are carried out in-place - there is no return value from this method.
            :param mask_path: A fully qualified path reference to the mask image - can be any size and may be colour,
                              as it will be converted as necessary within this method.
            :param annotate_img: A 'large' sized image onto which the contour will (optionally) be plotted - or None.
        """

        # The mask is resized to 'large' and converted to greyscale before finding contours on an inverted copy,
        #  and re-plotting those onto the existing _retain_mask.  Note that this approach is broadly equivalent to
        #  calling bitwise_or with the new mask and the existing _retain_mask, but gives more control and makes the
        #  contours available for annotation.  This will be marginally less efficient that bitwise_or, but is only
        #  called once or twice per clip so has negligible impact.
        image_mask = cv2.resize(cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE), self.base_frame.dimensions.large,
                                interpolation=cv2.INTER_NEAREST)
        contours = cv2.findContours(numpy.invert(image_mask),
                                    cv2.RETR_TREE,
                                    cv2.CHAIN_APPROX_SIMPLE)[self._contours_return_index]
        cv2.drawContours(self._retain_mask, contours, -1, (0, 0, 0), cv2.FILLED)
        # Add these contours to the record of contours added to the mask - as it is already a list, concatenate then
        self.retain_mask_contours += contours
        if annotate_img is not None:
            cv2.drawContours(annotate_img, contours, -1, Clip._annotate_line_colour, 1)

    #
    # ##### COMPOSITE CREATION METHODS
    #
    def get_composite_primary(self, segment, target_point, min_fraction_of_max_area, inc_fallback):
        """ Creates and returns a composite image containing the 'primary' subject, and optionally others.
            The primary subject is typically the nearest large subject to the target_point.  Other subjects may be
            added if inc_fallback=True.
            :param target_point: An (x, y) tuple specifying the target point where we want the subject to be closest to.
            :param min_fraction_of_max_area: Proportion of the largest subject in the clip, as a minimum size for the
                                             closest subject to target_point.  A very small value will effectively
                                             disregard the size.  A value of 1 will disregard position.  Should be in
                                             the range 0-1.
            :param inc_fallback: True/False, to determine whether to also try adding other subjects via fallback mode.
            :return: Returns the composite and its mask; which are also saved within clip.composites
        """
        # TODO: Handle cases where there are no subjects that meet the criteria in get_primary_subject, i.e. which
        # TODO:  aren't tracked, aren't already used, etc...
        # TODO: Update docs for segment!

        composite = self.base_frame.get_img('large')
        composite_mask = numpy.zeros(self.base_frame.dimensions_numpy.large, numpy.uint8)
        try:
            frame, subject = self._get_primary_subject(target_point, min_fraction_of_max_area)
        except EOFError:
            return False
        composite_added, composite, composite_mask = self._add_to_composite(frame=frame,
                                                                            subject=subject,
                                                                            composite=composite,
                                                                            composite_mask=composite_mask,
                                                                            allow_overlap=False,
                                                                            skip_is_used=False)
        if inc_fallback:
            # If adding additional fallback subjects it will save to clip.composites before returning, so not done here.
            composite, composite_mask = self.get_composite_fallback(segment=segment,
                                                                    composite=composite,
                                                                    composite_mask=composite_mask,
                                                                    interim=True,
                                                                    allow_overlap=False)
        segment.composites.append({'style': 'Primary', 'composite': composite, 'mask': composite_mask})
        return composite, composite_mask

    def get_complete_composite(self, segment, style='Complete'):
        # TODO: Documentation...
        try:
            self.get_composite_fallback(segment=segment, allow_overlap=True, style=style, skip_is_used=True)
        except EOFError:
            pass

    def get_composite_fallback(self, segment, composite=None, composite_mask=None, interim=False,
                               allow_overlap=False, style='Fallback', skip_is_used=False, latest_time=-1):
        """ Creates and returns a composite image containing every subject that's not already been handled elsewhere.
            This method acts as a fallback - the expectation should be that all subjects will be handled by a more
            sophisticated method which creates a more visually effective composite.  This should therefore over time
            be used less frequently, and only for unusual, abnormal or complex activity within clips.
            The composite is based on a 'large' copy of the original base_frame, and will add all active subjects that
            are not already used elsewhere, or captured within a track.  Optionally, an existing composite and
            composite_mask can be provided, which this will use as its basis (but still avoid any overlap).
            Optionally, this can avoid placing any subjects which would overlap with another - if not allowing overlap,
            then this method should be called repeatedly until it returns an EOFError exception, i.e. there are no more
            subjects to handle.
            :param composite: Optionally, an existing composite
            :param composite_mask: An existing composite_mask, covering all subjects in the composite to be preserved
            :param interim: Flag that this is contributing to a different style of composite, so don't save output.
            :param allow_overlap: Optionally, allow subjects to overlap on the composite.
            :param style: Optionally specify an alternative style label to describe the type of composite.
            :param skip_is_used: Optionally, ignore is_used flags, and also don't set is_used flag here
            :return: Returns the composite and its mask; which if not interim are also saved within clip.composites
        """

        if composite is not None and composite_mask is not None:
            # If we've supplied both a composite and composite_mask, then use those and therefore already have composite
            composite_any_added = True
        else:
            # Otherwise, create blank composite and composite_mask
            composite = self.base_frame.get_img('large')
            composite_mask = numpy.zeros(self.base_frame.dimensions_numpy.large, numpy.uint8)
            composite_any_added = False

        # Look through all frames and subjects for valid subjects, and try adding to the composite
        # for frame in self.frames.values():
        # UPDATE: Changed to using times to avoid errors if frames is modified by another thread whilst iterating
        for frame_time in range(segment.start_time + self.time_increment, segment.end_time, self.time_increment):
            frame = self.frames[frame_time]
            for subject in frame.subjects:
                if not subject.is_tracked and (not subject.is_used or skip_is_used) and subject.is_active:
                    # Note that _add_to_composite only TRIES to add this subject - however it will not do so if it
                    #  would overlap with a previous subject, and in that case just returns the input values
                    composite_added, composite, composite_mask = self._add_to_composite(frame=frame,
                                                                                        subject=subject,
                                                                                        composite=composite,
                                                                                        composite_mask=composite_mask,
                                                                                        allow_overlap=allow_overlap,
                                                                                        skip_is_used=skip_is_used)
                    composite_any_added = composite_any_added or composite_added
        if not composite_any_added:
            # Use EOFError Exception to highlight that there are no valid subjects remaining
            raise EOFError
        if not interim:
            segment.composites.append({'style': style, 'composite': composite, 'mask': composite_mask})
        return composite, composite_mask

    def _add_to_composite(self, frame, subject, composite, composite_mask, allow_overlap, skip_is_used):
        """ PRIVATE: Checks validity / overlap before then adding a subject to a composite, and updating its mask.
            :param frame: A valid frame object, containing the subject to add.
            :param subject: A valid subject object, which is the subject to add.
            :param composite: The existing composite, to which the subject will be added.
            :param composite_mask: A mask covering all subjects so-far added to the composite, to prevent overlap.
            :param allow_overlap: Boolean, allow subjects to overlap?
            :param skip_is_used: Optionally, ignore is_used flags, and also don't set is_used flag here
            :return: Returns a tuple (True/False is_added, composite, composite_mask)
        """
        subject_mask = subject.get_subject_mask(dilated=True, crop=False)
        # Check for overlap with previously added subjects, if necessary
        if not allow_overlap:
            overlap_with_added = numpy.bitwise_and(composite_mask, subject_mask)
            # This takes a very strict approach to checking for overlap, with zero pixels allowed
            if numpy.count_nonzero(overlap_with_added) > 0:
                # If there would be overlap, return False with the original unmodified composite / composite_mask
                return False, composite, composite_mask
        # Otherwise, mark the subject as used to prevent re-use later, and add the subject to the composite
        if not skip_is_used:
            subject.is_used = True
        composite = self._overlay_imgs(composite, frame.get_img('large'), subject_mask)
        composite_mask = numpy.bitwise_or(composite_mask, subject_mask)
        return True, composite, composite_mask

    @staticmethod
    def _overlay_imgs(base_img, subject_img, subject_mask):
        """ PRIVATE: Overlays a subject, with a specified mask, onto another (typically composite) image
            :param base_img: A colour image onto which we want to copy the subject
            :param subject_img: A colour image which contains the subject; should be the same size as the base_img
            :param subject_mask: A greyscale mask in which the subject is white (255) on a black (0) background
            :return: Returns an updated copy of the base_img, with the subject now overlaid
        """
        # The _retain_mask (used for the base_img background) is the inverse of the subject_mask, such that when they
        #  are combined via bitwise_or then each pixel will be non-zero for only one of the two sources.
        retain_mask = numpy.invert(subject_mask)
        base_retain = numpy.bitwise_and(base_img,
                                        cv2.cvtColor(retain_mask, cv2.COLOR_GRAY2BGR))
        subject_add = numpy.bitwise_and(subject_img,
                                        cv2.cvtColor(subject_mask, cv2.COLOR_GRAY2BGR))
        base_img = numpy.bitwise_or(base_retain, subject_add)
        return base_img

    #
    # ##### SEARCH FOR SUBJECTS
    #
    def _get_primary_subject(self, target_point, min_fraction_of_max_area):
        """ Searches all frames and subjects to find the nearest subject to the target_point, meeting minimum size.
            The primary subject is typically the nearest large subject to the target_point.
            :param target_point: An (x, y) tuple specifying the target point where we want the subject to be closest to.
            :param min_fraction_of_max_area: Proportion of the largest subject in the clip, as a minimum size for the
                                             closest subject to target_point.  A very small value will effectively
                                             disregard the size.  A value of 1 will effectively disregard target_point.
                                             This should be in the range 0-1.
            :return: Returns a tuple containing (frame, subject) for the primary subject
        """

        # Loop through all frames and subjects, and add a range of parameters to an array - ready for processing
        subject_params = []
        for frame in self.frames.values():
            for subject in frame.subjects:
                if not subject.is_tracked and not subject.is_used and subject.is_active:
                    subject_params.append({'area': subject.contour_area,
                                           'distance': subject.dist_from_point(target_point),
                                           'subject': subject,
                                           'frame': frame})
        # Filter the list of subjects to only include those at least specified fraction of the max sized subject
        if len(subject_params) == 0:
            raise EOFError
        min_area = max(s_param['area'] for s_param in subject_params) * min_fraction_of_max_area
        subject_params = [s_param for s_param in subject_params if s_param['area'] >= min_area]
        # Of the remaining, get the subject with the smallest distance from the target_point
        primary_subject_param = min(subject_params, key=lambda s_param: s_param['distance'])
        return primary_subject_param['frame'], primary_subject_param['subject']

    #

    #


class Segment:

    def __init__(self, index, start_time, end_time, required_for):
        self.index = index
        self.composites = []
        self.start_time = start_time
        self.end_time = end_time
        self.required_for = required_for.copy()
        self.last_segment = False
        self.trigger_zones = []
        self.plugins_complete = False

    def remove_requirement(self, requirement):
        try:
            # print('Removing req %s' % requirement)
            self.required_for.remove(requirement)
            if not len(self.required_for):
                # print('Clearing composites')
                self.composites.clear()
        except ValueError:
            # print('Value Error!')
            pass

    def add_requirement(self, requirement):
        if requirement not in self.required_for:
            self.required_for.append(requirement)

    def is_required(self):
        return len(self.required_for) > 0

    def is_required_for(self, required_for, bool_and=True):

        # Handle a list of requirements
        if isinstance(required_for, list):
            # If passed an empty list, will always be false, i.e. the segment is not required for that
            if len(required_for) == 0:
                return False
            # Otherwise, check each requirement and keep a running total (using AND or OR logic as necessary)
            final_req = bool_and
            for req in required_for:
                this_req = req in self.required_for
                if bool_and:
                    final_req = final_req and this_req
                else:
                    final_req = final_req or this_req
            return final_req

        # Alternative simple version if passed a single requirement
        else:
            return required_for in self.required_for

    # def clear_images(self):
    #     self.composites.clear()

    @staticmethod
    def segment_with_index(segments, index):
        matching_segments = [seg for seg in segments if seg.index==index]
        if len(matching_segments) > 0:
            return True, matching_segments.pop(0)
        else:
            return False, None

    # @staticmethod
    # def count_required_segments(segments):
    #     count = 0
    #     for segment in segments:
    #         if segment.is_required():
    #             count += 1
    #     return count
