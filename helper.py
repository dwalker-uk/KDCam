import sys
import os
import cv2
import numpy
from datetime import datetime, timedelta
from threading import Thread
import time
import shutil
import socket
from pympler import asizeof
from psutil import virtual_memory
import gc
import psutil


#
# ##### GLOBAL VARIABLES
#
_is_setup = False
_annotate_line_colour = None
_annotate_grid_colour = None
_timer_start_time = {}
_elapsed_last_time = {}
_lock_file = ''
_run_lock_async = False


#
# ##### SETUP METHOD
#
def setup(annotate_line_colour, annotate_grid_colour, lock_file):
    """

        :param annotate_line_colour:
        :param annotate_grid_colour:
    """
    global _is_setup, _annotate_line_colour, _annotate_grid_colour, _lock_file
    _annotate_line_colour = annotate_line_colour
    _annotate_grid_colour = annotate_grid_colour
    _lock_file = os.path.join(os.path.dirname(__file__), lock_file)
    _is_setup = True


#
# ##### SAFETY LOCK FILE HANDLING
#
def update_safe_lock():
    """
        TODO: Documentation
        :return:
    """
    with open(_lock_file, 'w') as f:
        print('%s' % timestamp(), file=f)


def start_safe_lock_async(interval_secs):
    """

        :return:
    """
    global _run_lock_async
    _run_lock_async = True
    update_safe_lock_thread = Thread(target=_update_safe_lock_async, args=(interval_secs,))
    update_safe_lock_thread.setDaemon(True)
    update_safe_lock_thread.start()


def stop_safe_lock_async():
    global _run_lock_async
    _run_lock_async = False


def _update_safe_lock_async(interval_secs):
    first_run = True
    while _run_lock_async:
        if first_run or secs_elapsed_since_last(secs=interval_secs, timer_id='lock_async'):
            with open(_lock_file, 'w') as f:
                print('%s' % timestamp(), file=f)
            first_run = False
        else:
            sleep(1)


def check_safe_lock(max_secs_for_safe_lock):
    """
        TODO: Documentation
        :return:
        """
    if len(sys.argv) >= 2 and sys.argv[1] == 'safe_start':
        try:
            with open(_lock_file, 'r') as f:
                time_since_updated_lock = timestamp_age(f.read(19))
                print('>>>%s<<<' % time_since_updated_lock)
                if time_since_updated_lock < max_secs_for_safe_lock:
                    return True
        except OSError:
            print('Lock-OSError')
            pass
        except ValueError:
            print('Lock-ValueError')
            pass
    return False


def remove_safe_lock():
    """
        TODO: Documentation
        :return:
    """
    stop_safe_lock_async()
    try:
        os.remove(_lock_file)
    except OSError:
        pass


#
# ##### TIME-RELATED METHODS
#
def timestamp(ms=False):
    """ Simply returns a formatted timestamp for the current system time """
    if ms:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
    else:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def datestamp(days_offset=0):
    """ Simply returns a formatted date for the current system time """
    return (datetime.now() + timedelta(days=days_offset)).strftime('%Y-%m-%d')


def secs_to_hhmmss(secs, integer_secs=True):
    if integer_secs:
        secs = int(secs)
    return str(timedelta(seconds=secs))


def timestamp_age(prev_timestamp):
    if len(prev_timestamp) == 19:
        return (datetime.now() - datetime.strptime(prev_timestamp, '%Y-%m-%d %H:%M:%S')).total_seconds()
    else:
        raise ValueError


def start_timer(timer_id='std'):
    """ Starts a timer running, for performance testing.
        Saves the current time in a module-level dictionary, using the timer_id.  Raise exception if the specified
        timer_id already exists.
        :param timer_id: An optional string to name this timer, for use when multiple timers are in use at once.
    """
    global _timer_start_time
    if timer_id in _timer_start_time:
        raise Exception('Duplicate timer_id requested - not allowed.')

    _timer_start_time[timer_id] = datetime.now()


def read_timer(timer_id='std'):
    global _timer_start_time
    if timer_id not in _timer_start_time:
        raise Exception('helper.read_timer must only be called after helper.start_timer, with a matching timer_id')
    delta_time = datetime.now() - _timer_start_time[timer_id]
    return '%4.2fs' % (delta_time.total_seconds())


def end_timer(timer_id='std'):
    """ Ends the current running timer, and returns the elapsed time (in seconds).
        Raises an exception if there isn't a matching timer_id already in the dictionary, meaning the timer hasn't been
        started.  Once done this removes the start_time for this timer_id from the dictionary, so we can be sure we're
        using the correct timings.
        :param timer_id: An optional string to name this timer - must match the timer_id specified in start_timer()
    """
    global _timer_start_time
    if timer_id not in _timer_start_time:
        raise Exception('helper.end_timer must only be called after helper.start_timer, with a matching timer_id')

    delta_time = datetime.now() - _timer_start_time[timer_id]
    del _timer_start_time[timer_id]
    return '%4.2fs' % (delta_time.total_seconds())


def clear_timer(timer_id='std'):
    """ Clears the current running timer - used if we break out of the timed activity early.
        Raises an exception if there isn't a matching timer_id already in the dictionary, meaning the timer hasn't been
        started.  Once done this removes the start_time for this timer_id from the dictionary, so we can be sure we're
        using the correct timings.
        :param timer_id: An optional string to name this timer - must match the timer_id specified in start_timer()
    """
    global _timer_start_time
    if timer_id not in _timer_start_time:
        raise Exception('helper.end_timer must only be called after helper.start_timer, with a matching timer_id')

    del _timer_start_time[timer_id]


def secs_elapsed_since_last(secs, timer_id='std'):
    global _elapsed_last_time
    if timer_id in _elapsed_last_time:
        delta_time = datetime.now() - _elapsed_last_time[timer_id]
        delta_seconds = delta_time.total_seconds()
        # Once the time difference exceeds the specified number of seconds, update the "last run" time and return True.
        if delta_seconds >= secs:
            _elapsed_last_time[timer_id] = datetime.now()
            return True
    else:
        # If the timer hasn't yet been initialised, set it to the current time
        _elapsed_last_time[timer_id] = datetime.now()
    return False


def clear_elapsed_timer(timer_id='std'):
    """ Clears the current running timer - used if we break out of the timed activity early.
        Raises an exception if there isn't a matching timer_id already in the dictionary, meaning the timer hasn't been
        started.  Once done this removes the start_time for this timer_id from the dictionary, so we can be sure we're
        using the correct timings.
        :param timer_id: An optional string to name this timer - must match the timer_id specified in start_timer()
    """
    global _elapsed_last_time
    if timer_id in _elapsed_last_time:
        del _elapsed_last_time[timer_id]


def hours_elapsed_since_last(hours, timer_id='std'):
    """ Tests whether the specified number of hours have passed since this last returned True.
        This is used to run actions on a regular schedule, i.e. every x hours.  On first-run, it will set the "last run"
        time to the current time, but return false.  The "last run" time is then only reset to current when the
        specified number of hours have elapsed, and the function returns true.
        :param hours: The number of hours to wait between returning True from this function.
        :param timer_id: An optional string to name this timer - allows multiple different delays simultaneously.
        :return: Returns True once every x hours - otherwise returns False.

    """
    return secs_elapsed_since_last(hours*3600, timer_id)


#
# ##### IMAGE ANNOTATION METHODS
#
def annotate_grid(annotate_img, spacing):
    """ Takes any image and plots grid-lines at specified spacing as an overlay.  Updated in-place - no return value
        :param annotate_img: An image (any size) - should be BGR colour space, otherwise overlay will be grey too
        :param spacing: Pixel spacing between subsequent grid lines (both horizontal and vertical)
    """
    if not _is_setup:
        raise Exception('Must call helper.setup() before using helper functions')

    max_y = annotate_img.shape[0]
    max_x = annotate_img.shape[1]
    for x in range(spacing-1, max_x, spacing):
        cv2.line(annotate_img, (x, 0), (x, max_y), _annotate_grid_colour, 1)
    for y in range(spacing-1, max_y, spacing):
        cv2.line(annotate_img, (0, y), (max_x, y), _annotate_grid_colour, 1)


def annotate_contour(annotate_img, contour_points=None, contour_points_dict=None, contour=None, contours=None):
    """ Takes any image and plots a contour as an overlay.  Updated in-place - no return value.
        The contour can be supplied as a simple python list of points in the format [[x,y],[x,y],[x,y],...]
        (contour_points=), as a numpy / OpenCV-compatible contour (contour=), or as a list of numpy / OpenCV-
        compatible contours (contours=).  If multiple are provided, only the first is used.
        :param annotate_img: An image (any size) - should be BGR colour space, otherwise overlay will be grey too
        :param contour_points: A simple python list, in the format [[x,y],[x,y],[x,y],...]
        :param contour: A numpy / OpenCV compatible contour
        :param contours: A list of numpy / OpenCV compatible contours
    """
    if not _is_setup:
        raise Exception('Must call helper.setup() before using helper functions')

    # Make individual contours into a single-element array, and convert to numpy format if needed
    if contour_points is not None:
        contours = [numpy.array(contour_points, dtype=numpy.int32)]
    elif contour_points_dict is not None:
        contours = []
        for contour_points in contour_points_dict:
            contours.append(numpy.array(contour_points['value'], dtype=numpy.int32))
    elif contour is not None:
        contours = [contour]
    elif isinstance(contours, list):
        pass
    else:
        raise Exception('Either contour=, contour_points= or contours= must be set for this function.')
    cv2.drawContours(annotate_img, contours, -1, _annotate_line_colour, 1)


def sleep(secs):
    time.sleep(secs)


def hostname():
    return socket.gethostname().split('.')[0]


def size_mb(test_object):
    size_bytes = asizeof.asizeof(test_object)
    return size_bytes / (1024 * 1024)


def memory_usage():
    process = psutil.Process(os.getpid())
    mem = process.memory_full_info().uss / float(2 ** 20)
    return mem  # In MB


def memory_free():
    mem = virtual_memory()
    return mem.available / (1024 * 1024)  # In MB


def clear_memory():
    gc.collect()


def enough_disk_space_for(mb_required, folder=os.path.dirname(__file__)):
    disk_free_space = shutil.disk_usage(folder).free
    if disk_free_space > mb_required * 1024 * 1024:
        return True
    else:
        return False


def get_temp_str():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return '%dC' % (int(f.read(5)) / 1000)
    except (OSError, ValueError):
        return 'N/A'
