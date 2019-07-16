import cv2
import numpy
from subject import Subject
from collections import namedtuple
DimensionLabels = namedtuple('DimensionLabels', 'source large medium small greyblur annotated')


class Frame:
    """ The Frame class captures individual frames from a clip / video, plus variations of the frame.

        This class is also able to find subjects within the frame, storing those as Subjects.
        Frame has required_for Frame.setup() and Frame.setup_time_increment() methods which must be called before the
        first Frame instance is created, in order to set key parameters.  Frame is then initialised via one of two
        custom initialisers - init_from_video or init_from_image, to which either an OpenCV VideoCapture object or
        an image is passed, plus the time at which the frame occurs within the clip.
        Frame is dependent on Subject, as a project-specific dependency.
    """

    #
    # ##### CLASS ATTRIBUTES
    #
    _is_setup = False
    _blur_pixel_width = None
    _absolute_intensity_threshold = None
    _morph_radius = None
    _subject_size_threshold = None
    # Two dimensions attributes are named tuples, with members accessed via .source, .large, .medium and .small
    dimensions = None           # dimensions is in (x, y) i.e. (width, height) format
    dimensions_numpy = None     # dimensions_numpy is in (y, x) format, for easier use with numpy arrays

    _is_setup_time_increment = False
    _time_increment = None

    # findContours returns (image, contours, hierarchy) in OpenCV 3, but (contours, hierarchy) in OpenCV 2 and OpenCV 4
    _contours_return_index = 1 if cv2.__version__.startswith('3.') else 0

    #
    # ##### SETUP METHODS
    #
    @staticmethod
    def setup(blur_pixel_width, absolute_intensity_threshold, morph_radius, subject_size_threshold,
              source_size_x, source_size_y, large_size_x, medium_size_x, small_size_x):
        """ Frame.setup() must be called prior to creating a Frame instance.
            Typically this would be at the top of the main file.
            :param blur_pixel_width: Image processing works best on blurred images - this controls the amount of blur
            :param absolute_intensity_threshold: In range 0-255, as min threshold for considering a pixel as different
            :param morph_radius: Morph is used to fill small gaps in difference masks - radius in pixels
            :param subject_size_threshold: Absolute num pixels in a contour for an area to be considered a subject
            :param source_size_x: Pixel width of the original source image / video
            :param source_size_y: Pixel height of the original source image / video
            :param large_size_x: Desired pixel width for a 'large' version of any image
            :param medium_size_x: Desired pixel width for a 'medium' version of any image
            :param small_size_x: Desired pixel width for a 'small' version of any image
        """
        Frame._is_setup = True
        Frame._blur_pixel_width = blur_pixel_width
        Frame._absolute_intensity_threshold = absolute_intensity_threshold
        Frame._morph_radius = morph_radius
        Frame._subject_size_threshold = subject_size_threshold
        # Dimensions are saved into a DimensionLabels namedtuple - this is immutable, so must all be set at once and
        #  cannot be changed later.  dimensions_numpy simply reverses the size tuple of dimensions, via [::-1].
        Frame.dimensions = DimensionLabels(source=(source_size_x, source_size_y),
                                           large=(large_size_x,
                                                  int(source_size_y / source_size_x * large_size_x)),
                                           medium=(medium_size_x,
                                                   int(source_size_y / source_size_x * medium_size_x)),
                                           small=(small_size_x,
                                                  int(source_size_y / source_size_x * small_size_x)),
                                           greyblur=(large_size_x,
                                                     int(source_size_y / source_size_x * large_size_x)),
                                           annotated=(large_size_x,
                                                      int(source_size_y / source_size_x * large_size_x)))
        Frame.dimensions_numpy = DimensionLabels(source=Frame.dimensions.source[::-1],
                                                 large=Frame.dimensions.large[::-1],
                                                 medium=Frame.dimensions.medium[::-1],
                                                 small=Frame.dimensions.small[::-1],
                                                 greyblur=Frame.dimensions.large[::-1],
                                                 annotated=Frame.dimensions.large[::-1])
        Subject.setup_dimensions_numpy(Frame.dimensions_numpy.large)

    @staticmethod
    def setup_time_increment(time_increment):
        """ Frame.setup_time_increment() must be called prior to creating a Frame instance.
            Typically this would be called as part of the Clip.setup() method, when time_increment is established.
            :param time_increment: Time in milliseconds between each frame (approx, dependent on clip timing structure)
        """
        Frame._time_increment = time_increment
        Frame._is_setup_time_increment = True

    #
    # ##### INIT METHODS
    #
    # @classmethod
    # def init_from_video(cls, video_capture, time, time_out_of_sync=False):
    #     """ Custom initialiser, for when a video stream is used - extracts the frame from the video stream.
    #         :param video_capture: A valid OpenCV VideoCapture object
    #         :param time: The time (in milliseconds) within the video to extract the frame.
    #         :param time_out_of_sync: Used to allow frames not a multiple of _time_increment; must be explicit
    #         :return: Returns a new Frame object, created by the primary __init__ method.
    #     """
    #
    #     # Seek to the correct part of the video, then read the frame
    #     video_capture.set(cv2.CAP_PROP_POS_MSEC, time)
    #     capture_success, source_frame_img = video_capture.read()
    #     if not capture_success:
    #         # No frames remaining - calling function should handle this as simply having reached end of the video
    #         raise EOFError
    #     return cls(source_frame_img, time, time_out_of_sync)

    @classmethod
    def init_from_video_sequential(cls, video_capture, time, frames_required_for, time_out_of_sync=False):
        """ Custom initialiser, for when a video stream is used - extracts the frame from the video stream.
            TODO: Update docs, tidy, etc
            :param video_capture: A valid OpenCV VideoCapture object
            :param time: The time (in milliseconds) within the video to extract the frame.
            :param time_out_of_sync: Used to allow frames not a multiple of _time_increment; must be explicit
            :return: Returns a new Frame object, created by the primary __init__ method.
        """
        prev_time = video_capture.get(cv2.CAP_PROP_POS_MSEC)
        if prev_time <= time:
            while True:
                capture_success = video_capture.grab()
                if not capture_success:
                    raise EOFError
                this_time = video_capture.get(cv2.CAP_PROP_POS_MSEC)
                if prev_time <= time <= this_time:
                    capture_success, source_frame_img = video_capture.retrieve()
                    if not capture_success:
                        raise EOFError
                    return cls(source_frame_img, time, time_out_of_sync, frames_required_for)
                prev_time = this_time
        else:
            # If for some reason we're getting frames out of sequence, then use the slower seek method to get the frame
            print('*** WARNING *** - GETTING FRAME OUT OF SEQUENCE - SLOW!')
            video_capture.set(cv2.CAP_PROP_POS_MSEC, time)
            capture_success, source_frame_img = video_capture.read()
            if not capture_success:
                # No frames remaining - calling function should handle this as simply having reached end of the video
                raise EOFError
            return cls(source_frame_img, time, time_out_of_sync, frames_required_for)

    @classmethod
    def init_from_image(cls, source_img, time, frames_required_for, time_out_of_sync=False):
        """ Custom initialiser, for when a image is the source of the frame - this is used directly.
            :param source_img: An image, matching the pre-defined size expected for a source frame.
            :param time: Will be recorded as part of the frame, but note this can be set arbitrarily.
            :param time_out_of_sync: Used to allow frames not a multiple of _time_increment; must be explicit
            :return: Returns a new Frame object, created by the primary __init__ method.
        """
        return cls(source_img, time, time_out_of_sync, frames_required_for)

    def __init__(self, source_img, time, time_out_of_sync, frames_required_for):
        """ PRIVATE: Create new instance of Frame - shouldn't be called directly, use init_from_video/image instead!
            This checks that adequate setup has been carried out, and that the frame size is as expected.
            Key variables are then setup and prepared for later use.
            :param source_img: Requires a valid image, of the expected size, representing the source frame
            :param time: The time in milliseconds at which we want to read the frame.
            :param time_out_of_sync: Used to allow frames not a multiple of _time_increment; must be explicit
        """

        # Check here that Frame class properties are set
        if not Frame._is_setup:
            raise Exception('Must call Frame.setup before creating a Frame instance')
        if not Frame._is_setup_time_increment:
            raise Exception('Must call Frame.setup_time_increment before creating a Frame instance')

        # Check that the source_img is of the expected dimensions
        if not Frame.dimensions_numpy.source == source_img.shape[:2]:
            raise Exception('New Frame source image / video dimensions are not as expected.')

        # Check that the time is a multiple of time_increment - or if not, that the calling function explicitly
        #  recognises that (via setting the time_out_of_sync parameter).  Otherwise would cause issues with previous /
        #  next frames, identifying subjects, etc.
        # TODO: Check implications of removing this - causes issues if we have to extend the interval after already
        # TODO:  resetting base_frame to be e.g. 1000 or 3000ms.
        self._time_out_of_sync = time_out_of_sync
        # if time % Frame._time_increment != 0 and not self._time_out_of_sync:
        #     raise Exception('New Frame time must be a multiple of time_increment, unless explicitly time_out_of_sync')

        # Initialise other variables for this instance of frame - most are only set when first required_for
        self.time = time
        self._img = {'source': source_img, 'large': None, 'medium': None, 'small': None,
                     'greyblur': None, 'annotated': None}

        # _tested_subjects allows us to know if empty subjects means there are no subjects, or just haven't checked yet
        self._tested_subjects = False
        self._tested_subject_activity = False
        self.subjects = []  # Stores a list of subjects within this frame, as a list of Subject objects
        self.audit = {}     # Stores interim steps of calculations, images, etc for debug / explainability

        self.required_for = frames_required_for.copy()
        # Frame._required_for.copy()    # List of strings denoting what the frame is expected to be needed for
                                                      # Used to ensure it's fulfilled all purposed before deleting it

    #
    # ##### PUBLIC METHODS
    #
    def get_img(self, img_type):
        """ Public method to return a version of the image matching img_type argument.
            This will either be a simple resized version (from the original source frame), or a version converted
            to greyscale and blurred, or a specific copy used for annotations.
            :param img_type: A string, either 'source', 'large', 'medium', 'small', 'greyblur' or 'annotated'.
            :return: Returns the requested image.
        """

        if self._img[img_type] is None:
            if img_type == 'source':
                # There should always be a source image already, which can just be returned - if not, something wrong!
                raise Exception('Frame.get_img() called without being properly initiated - source img not set.')
            elif img_type == 'greyblur':
                # greyblur always uses a 'large' image, with blurring applied after converting to greyscale
                self._img[img_type] = cv2.GaussianBlur(cv2.cvtColor(self.get_img('large'), cv2.COLOR_BGR2GRAY),
                                                       (Frame._blur_pixel_width, Frame._blur_pixel_width), 0)
            elif img_type == 'annotated':
                # annotated creates a copy of the 'large' image, used primarily for debugging / understanding the frame
                self._img[img_type] = self.get_img('large').copy()
            elif img_type in ['large', 'medium', 'small']:
                self._img[img_type] = cv2.resize(self._img['source'],
                                                 getattr(Frame.dimensions, img_type),
                                                 interpolation=cv2.INTER_AREA)
            else:
                # No other img_type than those listed above is valid - must be typo somewhere!
                raise Exception('Invalid img_type for Frame.get_img().')
        return self._img[img_type]

    # def clear_imgs(self):
    #     """
    #         TODO: Full documentation
    #         :return:
    #     """
    #     for img_type in ['source', 'large', 'medium', 'small', 'annotated']:
    #         self._img[img_type] = None

    # def clear_audit(self):
    #     """
    #         TODO: Documentation
    #         :return:
    #     """
    #     self.audit.clear()

    def remove_requirement(self, requirement):
        # Handle requirement as both a list of requirements, or as a single item by turning into a list of one
        if type(requirement) is not list:
            requirement = [requirement]
        for req in requirement:
            try:
                self.required_for.remove(req)
            except ValueError:
                pass

    def add_requirement(self, requirement):
        # Handle requirement as both a list of requirements, or as a single item by turning into a list of one
        if type(requirement) is not list:
            requirement = [requirement]
        for req in requirement:
            if req not in self.required_for:
                self.required_for.append(req)

    def is_required(self):
        return len(self.required_for) > 0

    def is_required_for(self, required_for):
        return required_for in self.required_for

    def get_subjects(self, base_frame, retain_mask):
        """ Calculates what subjects exist in this frame, and saves those in an array of Subject objects.
            Subjects are identified by comparing the current frame with a base_frame, looking for changed pixels
            between the two and then morphing those changed pixels in order to fill in small gaps.
            Those differences are then turned into a series of contours, which are then tested individually
            by re-plotting them, applying the _retain_mask (to ignore noisy areas, bushes, etc) and then re-converting
            to contours in order to check whether the size (excluding any masked areas) is large enough to be considered
            a subject of interest.  If so, the subject is created, but notably with the original pre-masked contour -
            this ensures that if subjects happen to overlap a masked area, the whole subject is still captured.
            :param base_frame: A Frame object representing the base_frame for comparison.
            :param retain_mask: A numpy array mask marking as non-zero those areas to be retained.
            :return: A list of subjects is returned - this may be empty if there are no subjects.
        """

        # Perform a per-pixel comparisons between the two frames, and basic manipulation to give a cleaner difference.
        self.audit['base_comparison_basic'] = cv2.absdiff(base_frame.get_img('greyblur'), self.get_img('greyblur'))
        self.audit['base_comparison_absolute'] = cv2.threshold(self.audit['base_comparison_basic'],
                                                               Frame._absolute_intensity_threshold,
                                                               255,
                                                               cv2.THRESH_BINARY)[1]  # [1] returns just the image
        self.audit['base_comparison_morph'] = cv2.morphologyEx(self.audit['base_comparison_absolute'],
                                                               cv2.MORPH_CLOSE,
                                                               numpy.ones((Frame._morph_radius,
                                                                           Frame._morph_radius), numpy.uint8))

        # Generate contours from the comparison image (numpy array), so we can work on each contour in turn
        morph_contours = cv2.findContours(self.audit['base_comparison_morph'],
                                          cv2.RETR_EXTERNAL,
                                          cv2.CHAIN_APPROX_SIMPLE)[self._contours_return_index]
        for morph_contour in morph_contours:
            # Re-create the contour as an image mask, but only one contour at a time - then apply _retain_mask
            morph_contour_img = numpy.zeros(Frame.dimensions_numpy.large, numpy.uint8)
            cv2.drawContours(morph_contour_img, [morph_contour], -1, (255, 255, 255), cv2.FILLED)
            masked_morph_contour_img = numpy.bitwise_and(morph_contour_img, retain_mask)

            # Once again revert back to contours, so we can loop through in turn and check their sizes (after masking)
            masked_morph_contours = cv2.findContours(masked_morph_contour_img,
                                                     cv2.RETR_EXTERNAL,
                                                     cv2.CHAIN_APPROX_SIMPLE)[self._contours_return_index]
            for masked_morph_contour in masked_morph_contours:
                masked_morph_area = cv2.contourArea(masked_morph_contour)
                if masked_morph_area > Frame._subject_size_threshold:
                    # Only if the masked area is above size_threshold, create a new subject - but use the original,
                    #  pre-masked contour to ensure the entire subject is included.
                    self.subjects.append(Subject(morph_contour))
                    break

        # Note that we've tested for subjects, in order to distinguish 'no subjects' from 'not yet tested for them'.
        # Also mark base frame as tested, as it can't have subjects as nothing to compare to - so not applicable.
        self._tested_subjects = True
        base_frame._tested_subjects = True
        return self.subjects

    def num_subjects(self, only_active=False):
        """ Counts the number of subjects within this frame.  Note get_subjects must be called before this!
            Not saved as a stored value, as it's very quick to calculate, and has variants with only_active.
            :param only_active: Boolean; count all subjects (=False), or just those marked as active (=True)
            :return: Returns the number of subjects within this frame, as an integer
        """
        if not self._tested_subjects:
            raise EOFError('Must run Frame.get_subjects() prior to calling num_subjects()')
        num_subjects = 0
        for subject in self.subjects:
            # If is_active is true, we always count it.  And if we're not counting only_active, then count everything.
            if subject.is_active or not only_active:
                num_subjects += 1
        return num_subjects

    def get_subjects_and_activity(self, base_frame, prev_frame, retain_mask):
        """
            TODO: Documentation etc
            :param base_frame:
            :param prev_frame:
            :param retain_mask:
            :return:
        """
        self.get_subjects(base_frame, retain_mask)
        for subject in self.subjects:
            # Checking whether subjects are active are based on comparison to the previous frame
            subject.test_if_active(prev_frame.get_img('greyblur'),
                                   self.get_img('greyblur'))
        self._tested_subject_activity = True
        # Base and Prev are also flagged as tested, as tests would either have been done before or are not relevant
        base_frame._tested_subject_activity = True
        prev_frame._tested_subject_activity = True
        return self.subjects
