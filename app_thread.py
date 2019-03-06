from threading import Thread


class AppThread:

    def __init__(self, **kwargs):
        self._exception = None
        self._thread = None
        self._abort = False
        self._is_complete = False

        self._thread = Thread(target=self.safety_wrapper, kwargs=kwargs)
        self._thread.start()

    def safety_wrapper(self, **kwargs):
        try:
            self.threaded_function(**kwargs)
            if not self._abort and not self._exception:
                self._is_complete = True
        except BaseException as exc:
            self._exception = exc
            return

    def threaded_function(self, **kwargs):
        """
            Must regularly check 'if self.should_abort(): return', and should continue running (i.e. not return) until
            the thread functionality is complete.  Expected exceptions should be handled within the function - unhandled
            exceptions are handled at a higher level, and will typically cause the app (or clip) to be restarted!
        """
        raise NotImplementedError('Template only - threaded_function method must be implemented!')

    def stop(self, wait_until_stopped):
        self._abort = True
        if wait_until_stopped:
            self._thread.join()

    def is_running(self):
        if self._exception:
            raise self._exception
        elif self._thread.isAlive():
            return True
        else:
            return False

    def is_complete(self):
        return self._is_complete

    def should_abort(self):
        if self._abort:
            return True
        else:
            return False


# class FrameGetter(AppThread):
#
#     def threaded_function(self, clip, max_mem_usage_mb, required_for):
#         time = clip.base_frame.time
#         while time <= clip.video_duration_secs * 1000:
#
#             if self.should_abort():
#                 return
#
#             if helper.memory_usage() > max_mem_usage_mb:
#                 helper.sleep(0.1)
#                 continue
#
#             if time not in clip.frames:
#                 try:
#                     clip.frames[time] = Frame.init_from_video_sequential(clip._video_capture, time, required_for)
#                     # if time == 30000:
#                     #     raise ValueError('Help!')
#                 except EOFError:
#                     # An alternative way to break out of the while loop, in case video ends prematurely
#                     break
#             time += clip.time_increment

