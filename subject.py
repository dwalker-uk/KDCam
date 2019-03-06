import cv2
import numpy
import math


class Subject:
    """ The Subject class captures individual areas of activity within a single frame - essentially, objects / subjects.

        Subject has required_for Subject.setup() and Subject.setup_dimensions_numpy() methods which must be called before
        the first Subject instance is created, in order to set key parameters.  Subject is then initialised with a
        contour representing the subject.
        Subject has no project-specific dependencies.
    """

    #
    # ##### CLASS ATTRIBUTES #####
    #
    _is_setup = False
    _bounds_padding = None
    _annotate_line_colour = None
    _absolute_intensity_threshold = None
    _min_difference_area_percent = None
    _min_difference_area_pixels = None
    _dilate_pixels = None

    _is_setup_dimensions_numpy = False
    _dimensions_numpy = None

    #
    # ##### SETUP METHODS #####
    #
    @staticmethod
    def setup(bounds_padding, annotate_line_colour, absolute_intensity_threshold, min_difference_area_percent,
              min_difference_area_pixels, dilate_pixels):
        """ Subject.setup() must be called prior to creating a Subject instance.
            Typically this would be at the top of the main file.
            :param bounds_padding:
            :param annotate_line_colour: A tuple in BGR format i.e. (b, g, r), with each value 0-255
            :param absolute_intensity_threshold: In range 0-255, as min threshold for considering a pixel as different
            :param min_difference_area_percent: Fraction (range 0-1) for % of difference in subject area to be active
            :param min_difference_area_pixels: Absolute pixels for difference in subject area to be considered active
            :param dilate_pixels: Number of pixels by which to dilate the subject contour mask
        """
        Subject._bounds_padding = bounds_padding
        Subject._annotate_line_colour = annotate_line_colour
        Subject._absolute_intensity_threshold = absolute_intensity_threshold
        Subject._min_difference_area_percent = min_difference_area_percent
        Subject._min_difference_area_pixels = min_difference_area_pixels
        Subject._dilate_pixels = dilate_pixels
        Subject._is_setup = True

    @staticmethod
    def setup_dimensions_numpy(dimensions_numpy):
        """ setup_dimensions_numpy() must be called prior to creating a Subject instance.
            Typically this would be called as part of the setup of Frame, when _dimensions will be first known.
            :param dimensions_numpy:
        """
        Subject._dimensions_numpy = dimensions_numpy
        Subject._is_setup_dimensions_numpy = True

    #
    # ##### INIT METHOD #####
    #
    def __init__(self, contour):
        """ Initialises the key parameters of a new subject, as defined by a contour.
            Provides methods and attributes which can be accessed later, providing other subject-related features.
            :param contour: should be in valid OpenCV (i.e. findContours) format.
        """

        # Check here that Subject class attributes are set
        if not Subject._is_setup:
            raise Exception('Must call Subject.setup before creating a Subject instance')
        if not Subject._is_setup_dimensions_numpy:
            raise Exception('Must call Subject.setup_dimensions_numpy before creating a Subject instance')

        # Save / initialise key values for use later
        self.contour = contour
        self.contour_dilated = self.contour_dilate()
        contour_moments = cv2.moments(contour)
        self.contour_center = (int(contour_moments['m10']/contour_moments['m00']),
                               int(contour_moments['m01']/contour_moments['m00']))
        self.contour_area = cv2.contourArea(contour)    # Returns the enclosed area of the contour, in pixels
        self.bounds = cv2.boundingRect(contour)         # Produces [x, y, w, h]
        # Note crop_params uses format [y1, y2, x1, x2]  - note usage for cropping images: image[y1: y2, x1: x2]
        self.crop_params = [max(self.bounds[1] - Subject._bounds_padding, 0),
                            min(self.bounds[1] + self.bounds[3] + Subject._bounds_padding,
                                Subject._dimensions_numpy[0]),
                            max(self.bounds[0] - Subject._bounds_padding, 0),
                            min(self.bounds[0] + self.bounds[2] + Subject._bounds_padding,
                                Subject._dimensions_numpy[1])]

        self._is_active = None
        self.is_tracked = False     # Set externally if added to a Track class
        self.is_used = False        # Set externally if used within a Composite image
        self.audit = {}             # Stores interim steps of calculations, images, etc for debug / explainability

    #
    # ##### PUBLIC PROPERTIES #####
    #
    @property
    def is_active(self):
        """ Returns True if subject is moving compared to previous frame; otherwise False - but must be explicitly
            calculated using Subject.test_if_active.
            Simple property which will raise an exception if it is called prior to being set.
        """
        if self._is_active is None:
            raise EOFError('Subject.is_active can only be called after Subject.test_is_active.')
        return self._is_active

    #
    # ##### OTHER PUBLIC METHODS #####
    #
    def get_cropped_img(self, img, annotate=False):
        """ Generates and returns a copy of the supplied image, cropped to just include this subject (plus padding).
            :param img: Should be a 'large' size image; can be colour or greyscale, but note annotation will be grey if
                        the supplied image is greyscale.
            :param annotate: If set to true, will also draw the contour onto the cropped image before it is returned.
            :return: Returns a cropped version of the image.
        """

        if not (img.shape[0] == Subject._dimensions_numpy[0] and img.shape[1] == Subject._dimensions_numpy[1]):
            raise Exception('Image provided to Subject.get_cropped_img is the incorrect size.  Should be large.')

        cropped_img = img[self.crop_params[0]: self.crop_params[1],
                          self.crop_params[2]: self.crop_params[3]].copy()      # Create a copy to prevent over-writing
        if annotate:
            cv2.drawContours(cropped_img, [self.contour], -1, Subject._annotate_line_colour, 1,
                             offset=(-self.crop_params[2], -self.crop_params[0]))
        return cropped_img

    def test_if_active(self, prev_img_greyblur, this_img_greyblur):
        """ Compares the previous frame to current frame, only within the region of the subject, to determine activity.
            Note that a subject is considered 'active' if the difference between the previous and current frame, just
            within the subject contour boundary, is more than x% of the total area, or an area of at least ypx.
            :param prev_img_greyblur: Must be the 'large' size greyblur image for the previous frame.
            :param this_img_greyblur: Must be the 'large' size greyblur image for the current frame.
            :return: Returns boolean, describing whether the subject is considered active.
        """

        # Get just the cropped areas of each image, then get a difference _retain_mask of them
        self.audit['prev_cropped_img'] = self.get_cropped_img(prev_img_greyblur)
        self.audit['this_cropped_img'] = self.get_cropped_img(this_img_greyblur)
        self.audit['prev_basic'] = cv2.absdiff(self.audit['prev_cropped_img'],
                                               self.audit['this_cropped_img'])
        self.audit['prev_absolute'] = cv2.threshold(self.audit['prev_basic'],
                                                    Subject._absolute_intensity_threshold,
                                                    255,
                                                    cv2.THRESH_BINARY)[1]  # Note [1] returns just the array / image

        # Create a _retain_mask for just the subject area, and apply this to the difference _retain_mask to ensure only
        # differences within the subject contour are considered
        self.audit['subject_mask'] = self.get_subject_mask(crop=True)
        self.audit['prev_masked_absolute'] = numpy.bitwise_and(self.audit['prev_absolute'],
                                                               self.audit['subject_mask'])

        # Calculate the number of pixels which have changed sufficiently, then check if that exceeds defined threshold
        self.audit['difference_area'] = numpy.count_nonzero(self.audit['prev_masked_absolute'])
        if (self.audit['difference_area'] / self.contour_area > Subject._min_difference_area_percent
                or self.audit['difference_area'] > Subject._min_difference_area_pixels):
            # More than x% or ypx of previous difference contour_area is still different, hence object still moving
            self._is_active = True
        else:
            self._is_active = False
        return self._is_active

    def get_subject_mask(self, dilated=False, crop=False, invert=False):
        """ Creates an 'include _retain_mask' for the subject, i.e. non-zero (255) where the subject is.
        The default is for the background to be zeros, with the subject as 255's (white / non-zero).
        :param dilated: Boolean; if true, returns a dilated contour, rather than the original.
        :param crop: Boolean; if true crops to the subject contour + padding boundary.
        :param invert: Boolean; if true the subject is 0's, whilst the background is 255's.
        :return: The selected _retain_mask, as a numpy array.
        """

        # Prepare _dimensions, offset values, base _retain_mask and fill colour depending on options chosen.
        if crop:
            dimensions_numpy = (self.crop_params[1] - self.crop_params[0],
                                self.crop_params[3] - self.crop_params[2])
            offset = (-self.crop_params[2],
                      -self.crop_params[0])
        else:
            dimensions_numpy = Subject._dimensions_numpy
            offset = (0, 0)
        if invert:
            subject_mask = numpy.ones(dimensions_numpy, numpy.uint8) * 255
            fill_colour = (0, 0, 0)
        else:
            subject_mask = numpy.zeros(dimensions_numpy, numpy.uint8)
            fill_colour = (255, 255, 255)

        # Draw the subject on the _retain_mask, using the selected options, and return it.
        if dilated:
            selected_contour = self.contour_dilated
        else:
            selected_contour = self.contour
        cv2.drawContours(subject_mask, [selected_contour], -1, fill_colour, cv2.FILLED, offset=offset)
        return subject_mask

    def contour_dilate(self):
        """ Generates and returns a dilated version of the contour, to give cleaner edges to subjects when composited.
            Amount of dilation is set within Subject.setup().  The mask itself is not currently saved; just the contour.
            :return: Returns a single dilated contour.
        """
        subject_mask = numpy.zeros(Subject._dimensions_numpy, numpy.uint8)
        cv2.drawContours(subject_mask, [self.contour], -1, (255, 255, 255), cv2.FILLED)
        subject_mask = cv2.morphologyEx(subject_mask,
                                        cv2.MORPH_DILATE,
                                        numpy.ones((Subject._dilate_pixels, Subject._dilate_pixels), numpy.uint8))
        contour_dilate = cv2.findContours(subject_mask,
                                          cv2.RETR_EXTERNAL,
                                          cv2.CHAIN_APPROX_SIMPLE)[1]
        # As we start with only one contour, and are dilating it, we're guaranteed to still only have one - hence [0]
        return contour_dilate[0]

    def dist_from_point(self, point_xy):
        """ Calculate and return the distance (in pixels) of the centre of the subject from the specified point.
            This is calculated with simple trigonometry = sqrt(x^2 + y^2)
            :param point_xy: A tuple specifying the point from which to measure, as (x, y)
            :return: Returns the distance between the points, in pixels
        """
        return math.sqrt((abs(point_xy[0] - self.contour_center[0]) ** 2) +
                         (abs(point_xy[1] - self.contour_center[1]) ** 2))

    # NEW:
    def within_trigger_zone(self, trigger_zones):
        results = {}
        for trigger_zone in trigger_zones:
            if trigger_zone['type'] == 'contour':
                contour = numpy.array(trigger_zone['value'], dtype=numpy.int32)
                tz_mask = numpy.zeros(Subject._dimensions_numpy, numpy.uint8)
                cv2.drawContours(tz_mask, [contour], -1, (255, 255, 255), cv2.FILLED)

                if tz_mask[self.contour_center[1], self.contour_center[0]] == 255:
                    results[trigger_zone['label']] = True
                else:
                    results[trigger_zone['label']] = False
        return results

