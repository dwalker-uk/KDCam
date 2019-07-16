import os
import glob
import shutil
import cv2
import time
from datetime import datetime


def get_pending_video_list(folder):
    """  """
    return [f for f in sorted(os.listdir(folder)) if f.endswith('.mp4')]


def get_file_metadata(folder, video_filename):
    """  """
    # SAMPLE FILENAME: XXCam_01_20180517203949574.mp4
    #                  XXXXX_XX_YYYYMMDDHHMMSSmmm.mp4
    #                  XXCam-20180502-1727-34996.mp4
    #                  XXCam-01-20180502-1727-34996.mp4
    basename, extension = os.path.splitext(video_filename)
    filename_parts_u = basename.split('_')
    filename_parts_d = basename.split('-')
    if len(filename_parts_u) == 3 and filename_parts_u[2].isdigit() and len(filename_parts_u[2]) == 17:
        file_date = filename_parts_u[2][0:8]
        file_time1 = filename_parts_u[2][8:12]
        file_time2 = filename_parts_u[2][12:17]
        basename_new = '%s-%s-%s-%s' % (filename_parts_u[0], file_date, file_time1, file_time2)
    elif (len(filename_parts_d) == 4 and filename_parts_d[1].isdigit() and len(filename_parts_d[1]) == 8
            and filename_parts_d[2].isdigit() and len(filename_parts_d[2]) == 4
            and filename_parts_d[3].isdigit() and len(filename_parts_d[3]) == 5):
        basename_new = basename
        file_date = filename_parts_d[1]
    elif (len(filename_parts_d) == 5 and filename_parts_d[2].isdigit() and len(filename_parts_d[2]) == 8
            and filename_parts_d[3].isdigit() and len(filename_parts_d[3]) == 4
            and filename_parts_d[4].isdigit() and len(filename_parts_d[4]) == 5):
        basename_new = basename
        file_date = filename_parts_d[2]
    else:
        basename_new = basename
        file_date = 'NO_DATE'

    return {'original': video_filename,
            'source_fullpath': os.path.join(folder, video_filename),
            'filename_new': '%s%s' % (basename_new, extension),
            'basename_new': basename_new,
            'basename_original': basename,
            'file_date': file_date
            }


def get_file_datetime(base_name):
    filename_parts = base_name.split('-')
    if (len(filename_parts) == 4 and filename_parts[1].isdigit() and len(filename_parts[1]) == 8
            and filename_parts[2].isdigit() and len(filename_parts[2]) == 4
            and filename_parts[3].isdigit() and len(filename_parts[3]) == 5):
        file_date = filename_parts[1]
        file_time = filename_parts[2]
        file_secs = filename_parts[3][0:2]
        return datetime.strptime('%s%s%s' % (file_date, file_time, file_secs), '%Y%m%d%H%M%S')
    elif (len(filename_parts) == 5 and filename_parts[2].isdigit() and len(filename_parts[2]) == 8
            and filename_parts[3].isdigit() and len(filename_parts[3]) == 4
            and filename_parts[4].isdigit() and len(filename_parts[4]) == 5):
        file_date = filename_parts[2]
        file_time = filename_parts[3]
        file_secs = filename_parts[4][0:2]
        return datetime.strptime('%s%s%s' % (file_date, file_time, file_secs), '%Y%m%d%H%M%S')
    else:
        return None


def is_recently_modified(file_fullpath):
    """  """
    last_modified_time = os.path.getmtime(file_fullpath)
    current_time = time.time()
    if current_time - last_modified_time < 60:
        return True
    else:
        return False


def save_image(image, path, basename, descriptor='', date_subfolder=None, group_subfolder=None):
    """  """
    if date_subfolder is not None:
        path = os.path.join(path, date_subfolder)
    if group_subfolder is not None:
        path = os.path.join(path,group_subfolder)
    os.makedirs(path, exist_ok=True)
    is_orig = os.path.isfile(os.path.join(path, '%s-%s.jpg' % (basename, descriptor)))
    is_zero = os.path.isfile(os.path.join(path, '%s-%s00.jpg' % (basename, descriptor)))
    # If this file (or its ...0.jpg equivalent) already exists, add a counter and find the next available number
    if is_orig or is_zero:
        file_num = 0
        while True:
            file_num += 1
            if not os.path.isfile(os.path.join(path, '%s-%s%02d.jpg' % (basename, descriptor, file_num))):
                break
        output_path = os.path.join(path, '%s-%s%02d.jpg' % (basename, descriptor, file_num))
        if is_orig and not is_zero:
            # For consistency, if we have more than one file then rename the original to end ...0.jpg
            # TODO: THINK ABOUT HOW THIS IMPACTS LOG FILE OUTPUT...!
            os.rename(os.path.join(path, '%s-%s.jpg' % (basename, descriptor)),
                      os.path.join(path, '%s-%s00.jpg' % (basename, descriptor)))
    else:
        output_path = os.path.join(path, '%s-%s.jpg' % (basename, descriptor))

    cv2.imwrite(output_path, image)
    return output_path


def rename_basename_append(folder, subfolder, basename, append, conditional_suffix=''):
    prefix = os.path.join(folder, subfolder, basename)
    for base_file in glob.glob('%s-%s*' % (prefix, conditional_suffix)):
        suffix = base_file[len(prefix):]
        os.rename(base_file, '%s%s%s' % (prefix, append, suffix))


def move_to_done(video_done_folder, source_fullpath, file_date, filename_new):
    # Tidy up videos / move to 'done' folders
    os.makedirs(os.path.join(video_done_folder, file_date), exist_ok=True)
    video_path = os.path.join(video_done_folder, file_date, filename_new)
    os.rename(source_fullpath, video_path)
    return video_path


def remove_with_basename(source_folder, basename):
    for matching_file in [f for f in sorted(os.listdir(source_folder)) if f.startswith(basename)]:
        os.remove(os.path.join(source_folder, matching_file))


# def is_disk_space_low(folder, min_gb_remaining):
#     # shutil.disk_usage will raise an exception if folder doesn't exist - therefore use app folder if not found
#     if not os.path.isdir(folder):
#         folder = os.path.dirname(__file__)
#
#     disk_free_space = shutil.disk_usage(folder).free
#     if disk_free_space < min_gb_remaining * 1024 * 1024 * 1024:
#         return True, disk_free_space / (1024 * 1024 * 1024)
#     else:
#         return False, disk_free_space / (1024 * 1024 * 1024)

