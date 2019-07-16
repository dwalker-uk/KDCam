import os
import errno
from datetime import datetime
import file_handling
from kd_log import Log
import re


class Library:

    def __init__(self, folder_info):

        self.library = {}
        self.library_size = {}
        self.deleted_files = []
        self.deleted_folders = []
        self._cleanup_folder = None

        for folder, folder_path in folder_info:
            self.library[folder] = []
            self.library_size[folder] = 0

            for root_folder, folders, files in os.walk(folder_path):
                for file_name in [f for f in sorted(files, reverse=True) if f.endswith(('.mp4', '.jpg'))]:
                    full_path = os.path.join(root_folder, file_name)
                    basename, _ = os.path.splitext(file_name)
                    file_size = os.path.getsize(full_path)
                    self.library_size[folder] += file_size
                    self.library[folder].append({'fullpath': full_path,
                                                 'basename': basename,
                                                 'filesize': file_size})

    @property
    def cleanup_folder(self):
        if self._cleanup_folder is None:
            raise Exception('Must call Library.determine_cleanup_folder before trying to use the cleanup_folder.')
        else:
            return self._cleanup_folder

    def determine_cleanup_folder(self, target_size_ratios):
        comparative_size = {}
        for folder, size in self.library_size.items():
            comparative_size[folder] = size / target_size_ratios[folder]
        self._cleanup_folder = max(comparative_size, key=lambda k: comparative_size[k])

    def get_file_ages(self):
        for file in self.library[self.cleanup_folder]:
            timestamp = file_handling.get_file_datetime(file['basename'])
            if timestamp is not None:
                # Set file_age in hours
                file['file_age'] = (datetime.now() - timestamp).total_seconds() / 3600
            else:
                # If age is not specified in the filename, assume it is 48hrs old.  Will mean it's unlikely to be
                #  deleted which is fine, as these will usually be test files.
                file['file_age'] = 48

    def modify_ages(self, log_copy):
        """ Artificially transforms the 'age' of files in the library's cleanup_folder based on other factors.
            By modifying the age, this function ensures images or clips with certain characteristics are retained for
            longer.  Characteristics we do not value as highly will be made artificially older.
            TODO: UPDATE THIS!
            :return: No return value
        """
        for file in self.library[self.cleanup_folder]:
            try:
                [is_night, segments] = [(entry['is_night'], entry['segments']) for entry
                                        in log_copy if entry['basename'] == file['basename']][0]
                if is_night:
                    file['file_age'] = file['file_age'] * 1.5
                if not segments:
                    file['file_age'] = file['file_age'] * 2.5

            except ValueError:
                # If the lookup value isn't found, leave the file age un-modified.
                pass
            except IndexError:
                # If the lookup value isn't found, leave the file age un-modified.
                pass
            except TypeError:
                # TODO: Probably another underlying cause to this - got some errors around log_lookup above with
                # TODO:  TypeError NoneType object not iterable.  Unclear which variable is None..?
                pass

    # def modify_ages(self, log_lookup, log_name):
    #     """ Artificially transforms the 'age' of files in the library's cleanup_folder based on other factors.
    #         By modifying the age, this function ensures images or clips with certain characteristics are retained for
    #         longer.  Characteristics we do not value as highly will be made artificially older.
    #         :param log_lookup: A function for looking up log values, which must take four arguments:
    #                                 - log_name
    #                                 - the basename of each file in turn
    #                                 - the dictionary key for the basename field ('basename')
    #                                 - a list of keys to fetch from the log
    #                             It must then return a list returning the requested keys, and an empty list if no matches
    #         :param log_name: The name of the log holding the values we want to lookup
    #         :return: No return value
    #     """
    #     for file in self.library[self.cleanup_folder]:
    #         try:
    #             [is_night, segments] = log_lookup(log_name, file['basename'], 'basename', ['is_night', 'segments'])
    #             if is_night:
    #                 file['file_age'] = file['file_age'] * 1.5
    #             if not segments:
    #                 file['file_age'] = file['file_age'] * 2.5
    #
    #         except ValueError:
    #             # If the lookup value isn't found, leave the file age un-modified.
    #             pass
    #         except TypeError:
    #             # TODO: Probably another underlying cause to this - got some errors around log_lookup above with
    #             # TODO:  TypeError NoneType object not iterable.  Unclear which variable is None..?
    #             pass

    def do_cleanup(self, min_gb_to_remove, min_remaining_gb, gb_free_space):

        gb_to_remove = max(min_gb_to_remove, min_remaining_gb-gb_free_space)
        Log.add_entry('activity_log', 'Removing %.2fGB of files!' % gb_to_remove)

        self.library[self.cleanup_folder].sort(key=lambda k: k['file_age'])
        total_size_removed = 0
        while total_size_removed <= gb_to_remove * 1024 * 1024 * 1024:
            # Get the oldest file, and remove it from the end of the list
            try:
                file_to_delete = self.library[self.cleanup_folder].pop()
            except IndexError:
                break

            # Keep a running total of the size of files removed, delete it from system, and save that record
            total_size_removed += file_to_delete['filesize']
            try:
                os.remove(file_to_delete['fullpath'])
            except OSError:
                print('ERROR CANNOT REMOVE FILE - CHECK REASON, MAYBE PERMISSIONS??')
                Log.add_entry('activity_log', 'ERROR - Cannot remove file (OSError).')
            self.deleted_files.append(file_to_delete)

            # Try removing the folder - this will only work if the folder is empty (used for cleaning up), else ignored
            try:
                os.rmdir(os.path.dirname(file_to_delete['fullpath']))
            except OSError as e:
                if e.errno == errno.ENOTEMPTY:
                    continue
            else:
                self.deleted_folders.append(os.path.dirname(file_to_delete['fullpath']))

    def basenames(self):
        basenames = []
        for folder in self.library.keys():
            for file in self.library[folder]:
                basenames.append(file['basename'])
        return basenames

    def basenames_setlist(self):
        basenames_set = set()
        basenames_list = []
        for folder in self.library.keys():
            for file in self.library[folder]:
                pattern = r'^KDCam-\d{8}-\d{4}-\d{5}'
                true_basename = re.match(pattern, file['basename'])
                if true_basename:
                    basenames_set.add(true_basename.group())
                else:
                    basenames_list.append(file['basename'])
        return basenames_set, basenames_list

