import json
import helper
from app_thread import AppThread


class Log:
    """

    """
    # TODO: Remove the need for log_data_saved by introducing dynamic access to log file, via a queue and a separate
    # TODO:  helper function that waits in a loop until the queued request has been satisfied.
    # TODO: Or at least make full use of log_data_saved_valid to make sure we're all up-to-date!

    agg_names = []
    agg_fullpaths = {}
    agg_spec = {}
    agg_logs_needed = {}
    agg_pending_update = {}
    agg_update_confirmation = {}
    # agg_do_update = True

    names = []
    fullpaths = {}
    pending_data = {}
    data_confirmation = {}
    pending_removal = {}
    removal_confirmation = {}
    pending_filter = {}
    filter_confirmation = {}
    simple_list = {}
    pending_search = {}
    pending_lookup = {}
    pending_entire_log = {}
    # entire_log_data = {}
    # log_data_saved_valid = False
    print_also = {}
    finished = False
    async_running = False
    _thread = None

    def __init__(self, name, fullpath, simple, print_also=False):
        Log.names.append(name)
        Log.fullpaths[name] = fullpath
        Log.pending_data[name] = []
        Log.data_confirmation[name] = {}
        Log.pending_removal[name] = []
        Log.removal_confirmation[name] = {}
        Log.pending_filter[name] = []
        Log.filter_confirmation[name] = {}
        Log.simple_list[name] = simple
        Log.pending_search[name] = {}
        Log.pending_lookup[name] = {}
        Log.print_also[name] = print_also
        Log.pending_entire_log[name] = {}

    @staticmethod
    def define_aggregate(name, fullpath, specification):
        Log.agg_names.append(name)
        Log.agg_fullpaths[name] = fullpath
        Log.agg_spec[name] = specification
        Log.agg_pending_update[name] = False
        Log.agg_update_confirmation[name] = {}

        # Save a list of log names that this aggregate log depends on
        Log.agg_logs_needed[name] = []
        for spec_entry in Log.agg_spec[name]:
            if spec_entry['source'] not in Log.agg_logs_needed[name]:
                Log.agg_logs_needed[name].append(spec_entry['source'])

    @staticmethod
    def update_aggregate_log(name, wait_until_updated=False):
        Log.agg_pending_update[name] = True

        if wait_until_updated:
            # If want confirmation that it was updated, need to create a placeholder for that confirmation, and
            # then wait until the main log thread has processed the queue.  This runs in a different thread.
            if Log.agg_update_confirmation[name]:
                raise Exception('Should only ever have one agg_update_confirmation at a time.')
            Log.agg_update_confirmation[name] = {'complete': False}

            # Whilst waiting for confirmation, sleep to avoid excessive CPU usage.
            while not Log.agg_update_confirmation[name]['complete']:
                helper.sleep(0.05)

            # Once the main log thread has flagged it as complete, tidy up
            Log.agg_update_confirmation[name].clear()

    @staticmethod
    def search_log(name, search_value, search_key=None, match_partial=False):
        """ Search for matching values from a specific log, and return True or False.
            The search actually happens in the main log maintenance loop, and this function will wait until that's
            completed before it returns the result.
            :param name: Name of the log
            :param search_value: The string to search for
            :param search_key: If a dictionary-type log, the key to be searched
            :param match_partial: Boolean, determine whether sub-string matches are ok, or just the full string
            :return: Returns True or False whether the value was found
        """

        # Specify this search as pending for the main log maintenance loop
        Log.pending_search[name] = {'complete': False, 'search_value': search_value, 'search_key': search_key,
                                    'match_partial': match_partial, 'result': None}

        # Whilst waiting for confirmation, sleep to avoid excessive CPU usage.
        while not Log.pending_search[name]['complete']:
            helper.sleep(0.05)

        # Return the result once available
        return Log.pending_search[name]['result']

    @staticmethod
    def lookup(name, search_value, search_key=None, return_keys=None):
        """ Lookup specified values from a specific log, returning the value (or specific keys if a dict)
            The lookup actually happens in the main log maintenance loop, and this function will wait until that's
            completed before it returns the result.
            :param name: Name of the log
            :param search_value: The string to search for
            :param search_key: If a dictionary-type log, the key to be searched to match search_value
            :param return_keys: If a dict-type log, specify a list with one or more keys to return
            :return: Always returns a list, with one or more values (or key values if a dict-type log) - or empty list
        """

        # Specify this lookup as pending for the main log maintenance loop
        Log.pending_lookup[name] = {'complete': False, 'search_value': search_value, 'search_key': search_key,
                                    'return_keys': return_keys, 'result': None}

        # Whilst waiting for confirmation, sleep to avoid excessive CPU usage.
        while not Log.pending_lookup[name]['complete']:
            helper.sleep(0.05)

        # Return the result once available
        return Log.pending_lookup[name]['result']

    @staticmethod
    def get_entire_log(name):
        # TODO: Documentation
        Log.pending_entire_log[name] = {'available': False, 'result': None}

        # Whilst waiting for it to be available sleep to avoid excessive CPU usage.
        while not Log.pending_entire_log[name]['available']:
            helper.sleep(0.05)

        # Copy to temp variable, and then clear the saved log to reduce memory footprint
        return_value = Log.pending_entire_log[name]['result']
        Log.pending_entire_log[name].clear()

        return return_value

    @staticmethod
    def cleanup_log(name, valid_values, search_key=None, wait_for_deleted_entries=True):
        """ Used to clean-up the named log file, filtering out any entries without a match in the valid_values array.
            If search_key is None, the match will be tested against the entire entry, otherwise search_key
            is used as a key to the dictionary, and the value must match that.  Note that valid_values can be longer
            than the entry, and will still match - so a valid_values item of 'ABC1' will mean a log entry of 'ABC'
            is considered valid, providing the entire length of the log entry is found somewhere within valid_values.
            :param name: Name of the log
            :param valid_values: List of strings determining what is valid to remain in the log file.
            :param search_key: Optional, used only for dict log types to index the search field.
            :param wait_for_deleted_entries: Optional bool, will wait for and return a list of removed values if True.
            :return: Returns an array listing the deleted entries, or empty list if not waited for.
        """

        # Add the filter to the main log thread's queue to be actioned
        if Log.simple_list[name] or search_key:
            Log.pending_filter[name].append({'search_key': search_key, 'valid_values': valid_values})
        else:
            raise Exception('Must specify a search_key for cleanup_log for a dict-type log.')

        if wait_for_deleted_entries:
            # If want confirmation of what was deleted, need to create a placeholder for that list to be saved, and
            # then wait until the main log thread has processed the queue.  This runs in a different thread.
            if Log.filter_confirmation[name]:
                raise Exception('Should only ever have one filter_confirmation at a time.')
            Log.filter_confirmation[name] = {'complete': False, 'deleted_entries': []}

            # Whilst waiting for confirmation, sleep to avoid excessive CPU usage.
            while not Log.filter_confirmation[name]['complete']:
                helper.sleep(0.05)

            # Once the main log thread has flagged it as complete, tidy up and return
            deleted_entries = Log.filter_confirmation[name]['deleted_entries']
            Log.filter_confirmation[name].clear()
            return deleted_entries

        else:
            # If confirmation is not required_for, return an empty list immediately.
            return []

    @staticmethod
    def cleanup_log_by_date(name, num_days_to_keep, search_key=None):
        valid_values = []
        if num_days_to_keep < 1:
            raise Exception('Number of days to keep during log file cleanup must be an integer >= 1')
        for days_offset in range(0, num_days_to_keep):
            valid_values.append(helper.datestamp(-days_offset))
        return Log.cleanup_log(name, valid_values, search_key, False)

    @staticmethod
    def add_entry(name, new_data, wait_until_added=False):
        """ [CURRENTLY UNUSED] Add a new entry to the log file, and also print it if needed.
            The new_data should be either a string or a dict, depending on the type of log.  For simple log format, the
            string will be prefixed with a timestamp.
            Option to wait until that value is actually written, in the main log thread, before returning - helpful to
            keep the multiple threads in sync.
            :param name: Name of the log
            :param new_data: Either: string (for simple logs), else a dictionary (which can contain arbitrary keys)
            :param wait_until_added: Optional bool, to wait until the value is written before returning
            :return: No return value
        """

        # Add the data to the queue, ready to be written to the log within the main log processing thread
        if Log.simple_list[name]:
            Log.pending_data[name].append('%s - %s' % (helper.timestamp(ms=True), new_data))
        else:
            Log.pending_data[name].append(new_data)

        # If simple log entries are also required_for to be printed to the console, do that here - including the timestamp
        if Log.simple_list[name] and Log.print_also[name]:
            print('%s - %s' % (helper.timestamp(), new_data))

        # If required_for, wait until confirmed that this data has been successfully added in the main log thread.
        if wait_until_added:
            # If want confirmation that it was added, need to create a placeholder for that confirmation, and
            # then wait until the main log thread has processed the queue.  This runs in a different thread.
            if Log.data_confirmation[name]:
                raise Exception('Should only ever have one data_confirmation at a time.')
            Log.data_confirmation[name] = {'complete': False}

            # Whilst waiting for confirmation, sleep to avoid excessive CPU usage.
            while not Log.data_confirmation[name]['complete']:
                helper.sleep(0.05)

            # Once the main log thread has flagged it as complete, tidy up
            Log.data_confirmation[name].clear()

    @staticmethod
    def remove_entry(name, remove_value, key=None, wait_until_removed=False):
        """ Remove an entry from the log file that matches remove_value - and matching the key if a dict-type log.
            Option to wait until that value is actually removed, in the main log thread, before returning - helpful to
            keep the multiple threads in sync.
            :param name: Name of the log
            :param remove_value: Log entries matching this value will be removed
            :param key: For dict-type logs, will search under this key
            :param wait_until_removed: Optional bool, to wait until the value is written before returning
            :return: No return value
        """

        # Add the removals to the queue, ready to be removed from the log within the main log processing thread
        if Log.simple_list[name]:
            Log.pending_removal[name].append(remove_value)
        elif key:
            Log.pending_removal[name].append((key, remove_value))
        else:
            raise Exception('Invalid request to remove entry from Log - must supply key if Log is a dictionary!')

        # If required_for, wait until confirmed that this data has been successfully removed in the main log thread.
        if wait_until_removed:
            # If want confirmation that it was removed, need to create a placeholder for that confirmation, and
            # then wait until the main log thread has processed the queue.  This runs in a different thread.
            if Log.removal_confirmation[name]:
                raise Exception('Should only ever have one removal_confirmation at a time.')
            Log.removal_confirmation[name] = {'complete': False}

            # Whilst waiting for confirmation, sleep to avoid excessive CPU usage.
            while not Log.removal_confirmation[name]['complete']:
                helper.sleep(0.05)

            # Once the main log thread has flagged it as complete, tidy up
            Log.removal_confirmation[name].clear()

    # @staticmethod
    # def start_async():
    #     """ Simply start the log maintenance function in its own thread, which will then run continuously.
    #         :return: No return value
    #     """
    #     Log._thread = Thread(target=Log._update_log_async)
    #     Log._thread.start()
    #     Log.async_running = True
    #
    # @staticmethod
    # def stop_async(wait_until_finished=False):
    #     """ Stops the log processing, and if required_for waits for it to complete before returning.
    #         This is actioned via the _update_log_async loop is fully updated and completes.
    #         :return: No return value, but remains in this function until the loop is completed (if required_for)
    #     """
    #     Log.finished = True
    #     if wait_until_finished and Log.async_running:
    #         Log._thread.join()
    #
    # @staticmethod
    # def _update_log_async():
    #     """ Intended to run continuously, in its own thread, watching for changes and saving them quickly to file.
    #         Watches for pending data additions, removals, or application of filters to a range of logs, including
    #         aggregated logs.  All log actions are performed within this loop, to avoid any conflict or out-of-sync
    #         changes or actions.
    #         :return: No return value
    #     """
    #
    #     while True:
    #         log_data_for_agg = {}
    #         for agg_name in Log.agg_names:
    #             if Log.agg_pending_update[agg_name]:
    #                 for name in Log.agg_logs_needed[agg_name]:
    #                     if name not in log_data_for_agg:
    #                         log_data_for_agg[name] = []
    #
    #         for name in Log.names:
    #             # Update the named log if anything pending (add, remove, filter, search or lookup)
    #             if (Log.pending_data[name] or Log.pending_removal[name] or Log.pending_filter[name]
    #                     or Log.pending_search[name] or Log.pending_lookup[name] or (name in log_data_for_agg)):
    #                 log_data = []
    #                 log_data_changed = False
    #
    #                 # Load existing data from file, if there is any - otherwise, will work from an empty list
    #                 try:
    #                     with open(Log.fullpaths[name], 'r') as log_handle:
    #                         log_data = json.load(log_handle)
    #                 except (IOError, json.decoder.JSONDecodeError):
    #                     pass
    #
    #                 # Only perform actions which require an update to the log if there is sufficient disk-space
    #                 # Otherwise, these will be skipped and queued for later - the main program loop should ensure
    #                 #  that disk space is cleaned up quickly!
    #                 if helper.enough_disk_space_for(10):
    #
    #                     # Add any pending data to the log
    #                     while Log.pending_data[name]:
    #                         log_data.append(Log.pending_data[name].pop())
    #                         log_data_changed = True
    #
    #                         # If requested, provide confirmation that the data has been written
    #                         if Log.data_confirmation[name]:
    #                             Log.data_confirmation[name]['complete'] = True
    #
    #                     # Remove any pending data from the log
    #                     while Log.pending_removal[name]:
    #                         remove_value = Log.pending_removal[name].pop()
    #                         log_data_changed = True
    #
    #                         # Depending on the type of log, remove the data where it matches the specified value
    #                         if Log.simple_list[name] and isinstance(remove_value, str):
    #                             log_data[:] = [d for d in log_data if d != remove_value]
    #                         elif isinstance(remove_value, tuple):
    #                             log_data[:] = [d for d in log_data if d.get(remove_value[0]) != remove_value[1]]
    #                         else:
    #                             raise Exception('Invalid request to remove values from the Log')
    #
    #                         # If requested, provide confirmation that the data has been removed
    #                         if Log.removal_confirmation[name]:
    #                             Log.removal_confirmation[name]['complete'] = True
    #
    #                     # Apply any pending filters to clean-up data from the log
    #                     while Log.pending_filter[name]:
    #                         deleted_entries = []
    #                         pending_filter = Log.pending_filter[name].pop()
    #                         log_data_changed = True
    #
    #                         # Process the log in reverse, to maintain integrity of index values as entries are removed
    #                         for log_entry in reversed(log_data):
    #                             if Log.simple_list[name]:
    #                                 for valid_value in pending_filter['valid_values']:
    #                                     # Test for a matching value *up to the length of the log entry* - extra chars
    #                                     # at the end of valid_value will be ignored in the match
    #                                     if log_entry[:len(valid_value)] == valid_value[:len(log_entry)]:
    #                                         break   # Valid entry - keep it
    #                                 else:
    #                                     log_data.remove(log_entry)
    #                                     deleted_entries.append(log_entry)
    #                             elif pending_filter['search_key']:
    #                                 for valid_value in pending_filter['valid_values']:
    #                                     # Test for a matching value *up to the length of the log entry* - extra chars
    #                                     # at the end of valid_value will be ignored in the match
    #                                     if (log_entry[pending_filter['search_key']][:len(valid_value)] ==
    #                                             valid_value[:len(log_entry[pending_filter['search_key']])]):
    #                                         break   # Valid entry - keep it
    #                                 else:
    #                                     log_data.remove(log_entry)
    #                                     deleted_entries.append(log_entry[pending_filter['search_key']])
    #                             else:
    #                                 raise Exception('Invalid request to filter values in the log')
    #
    #                         # If requested, provide confirmation that the filter has been applied
    #                         if Log.filter_confirmation[name]:
    #                             Log.filter_confirmation[name]['deleted_entries'] = deleted_entries
    #                             Log.filter_confirmation[name]['complete'] = True
    #
    #                 # Perform any requested searches, based on the type of log
    #                 if Log.pending_search[name]:
    #                     Log.pending_search[name]['result'] = False
    #                     if Log.simple_list[name]:
    #                         if Log.pending_search[name]['match_partial']:
    #                             # Perform simple log search, including partial matches
    #                             if any(Log.pending_search[name]['search_value'] in d for d in log_data):
    #                                 Log.pending_search[name]['result'] = True
    #                         else:
    #                             # Perform simple log search, including only full matches
    #                             if Log.pending_search[name]['search_value'] in log_data:
    #                                 Log.pending_search[name]['result'] = True
    #                     elif Log.pending_search[name]['search_key']:
    #                         if Log.pending_search[name]['match_partial']:
    #                             # Perform dict log search, including partial matches
    #                             if any(Log.pending_search[name]['search_value'] in d for d
    #                                    in [i[Log.pending_search[name]['search_key']] for i in log_data]):
    #                                 Log.pending_search[name]['result'] = True
    #                         else:
    #                             # Perform dict log search, including only full string matches
    #                             if (Log.pending_search[name]['search_value'] in
    #                                     [i[Log.pending_search[name]['search_key']] for i in log_data]):
    #                                 Log.pending_search[name]['result'] = True
    #                     else:
    #                         raise Exception('Invalid search of log file requested.')
    #                     Log.pending_search[name]['complete'] = True
    #
    #                 # Perform any requested lookups, based on the type of log
    #                 if Log.pending_lookup[name]:
    #                     Log.pending_lookup[name]['result'] = []
    #                     if Log.simple_list[name]:
    #                         # Test for a matching value *up to the length of the log entry* - extra characters
    #                         # at the end of search_value will be ignored in the match.  For simple-type logs
    #                         for log_entry in log_data:
    #                             if log_entry == Log.pending_lookup[name]['search_value'][:len(log_entry)]:
    #                                 Log.pending_lookup[name]['result'] = log_entry
    #                                 break
    #                     elif Log.pending_lookup[name]['search_key']:
    #                         # Test for a matching value *up to the length of the log entry* - extra characters
    #                         # at the end of search_value will be ignored in the match.  For dict-type logs
    #                         for log_entry in log_data:
    #                             search_key = Log.pending_lookup[name]['search_key']
    #                             if (log_entry[search_key] ==
    #                                     Log.pending_lookup[name]['search_value'][:len(log_entry[search_key])]):
    #                                 Log.pending_lookup[name]['result'] = [log_entry[k] for k
    #                                                                       in Log.pending_lookup[name]['return_keys']]
    #                                 break
    #                     else:
    #                         raise Exception('Invalid lookup in log file requested.')
    #                     Log.pending_lookup[name]['complete'] = True
    #
    #                 # If required_for for an aggregate_log, save this log_data into this dict so it's available below
    #                 if name in log_data_for_agg:
    #                     log_data_for_agg[name] = log_data
    #
    #                 # Only re-save to file if anything has changed - if just searching then won't need to
    #                 if log_data_changed:
    #                     # Once log_data has been updated, re-sort it by timestamp (newest first)
    #                     if Log.simple_list[name]:
    #                         log_data.sort(reverse=True)
    #                     else:
    #                         log_data.sort(key=lambda k: k['timestamp'], reverse=True)
    #
    #                     # Save log_data back to file
    #                     with open(Log.fullpaths[name], 'w') as log_handle:
    #                         json.dump(log_data, log_handle, indent=2, sort_keys=True)
    #
    #                 # Delete log_data - if no longer needed (this decrements reference count), reduces memory footprint
    #                 del log_data
    #
    #             # If the entire log is flagged as finished, remove this specific log so we know it's up-to-date
    #             if Log.finished:
    #                 Log.names.remove(name)
    #
    #         # Update the aggregate logs, if required_for
    #         for agg_name in Log.agg_names:
    #             if Log.agg_pending_update[agg_name]:
    #                 for name in Log.agg_logs_needed[agg_name]:
    #                     if name not in log_data_for_agg:
    #                         # If this name isn't available, then can't update this aggregate log yet - let it loop again
    #                         break
    #
    #                 else:
    #                     # Only attempt to update the aggregate logs if there is sufficient disk space.
    #                     if helper.enough_disk_space_for(50):
    #                         # All required_for data was found, so continue
    #                         datestamp = helper.datestamp()
    #                         agg_data = []
    #
    #                         # Load existing agg log data from file, if there is any
    #                         try:
    #                             with open(Log.agg_fullpaths[agg_name], 'r') as agg_handle:
    #                                 agg_data = json.load(agg_handle)
    #                         except (IOError, json.decoder.JSONDecodeError):
    #                             pass
    #
    #                         # Remove any entry for current day from the aggregate file - we'll re-generate this below
    #                         agg_data[:] = [d for d in agg_data if d.get('date') != datestamp]
    #
    #                         # Create the aggregate entry for today, with a timestamp plus fields specified in agg_spec
    #                         agg_today = {'date': datestamp}
    #                         for agg_field in Log.agg_spec[agg_name]:
    #                             if Log.simple_list[agg_field['source']]:
    #                                 log_data_today = [d for d in log_data_for_agg[agg_field['source']] if
    #                                                   d[:10] == datestamp]
    #                             else:
    #                                 log_data_today = [d for d in log_data_for_agg[agg_field['source']] if
    #                                                   d.get('timestamp')[:10] == datestamp]
    #                             agg_today[agg_field['name']] = agg_field['function'](log_data_today)
    #                             del log_data_today
    #
    #                         # Add today's entry to any previous, and re-sort the list with newest first
    #                         agg_data.append(agg_today)
    #                         agg_data.sort(key=lambda k: k['date'], reverse=True)
    #
    #                         # Save the aggregate log to file
    #                         with open(Log.agg_fullpaths[agg_name], 'w') as agg_handle:
    #                             json.dump(agg_data, agg_handle, indent=2, sort_keys=True)
    #
    #                         # Delete agg_data if no longer needed (this decrements ref count), reduces memory footprint
    #                         del agg_data
    #
    #                         # Mark this aggregate log update as completed
    #                         Log.agg_pending_update[agg_name] = False
    #                         if Log.agg_update_confirmation[agg_name]:
    #                             Log.agg_update_confirmation[agg_name]['complete'] = True
    #
    #         # At the end of every loop, clear any data saved for the aggregate log to minimise memory usage
    #         log_data_for_agg.clear()
    #
    #         # Once all logs are finished, break out of this thread
    #         if Log.finished and len(Log.names) == 0:
    #             Log.async_running = False
    #             break
    #
    #         # Sleep at the end of each loop, to avoid over-processing in this thread when nothing is happening
    #         helper.sleep(0.01)


class LogThread(AppThread):

    def threaded_function(self):
        while True:

            if self.should_abort():
                return

            log_data_for_agg = {}
            for agg_name in Log.agg_names:
                if Log.agg_pending_update[agg_name]:
                    for name in Log.agg_logs_needed[agg_name]:
                        if name not in log_data_for_agg:
                            log_data_for_agg[name] = []

            for name in Log.names:
                # Update the named log if anything pending (add, remove, filter, search or lookup)
                if (Log.pending_data[name] or Log.pending_removal[name] or Log.pending_filter[name]
                        or Log.pending_search[name] or Log.pending_lookup[name] or (name in log_data_for_agg)
                        or Log.pending_entire_log[name]):
                    log_data = []
                    log_data_changed = False

                    # Load existing data from file, if there is any - otherwise, will work from an empty list
                    try:
                        with open(Log.fullpaths[name], 'r') as log_handle:
                            log_data = json.load(log_handle)
                    except (IOError, json.decoder.JSONDecodeError):
                        pass

                    # Only perform actions which require an update to the log if there is sufficient disk-space
                    # Otherwise, these will be skipped and queued for later - the main program loop should ensure
                    #  that disk space is cleaned up quickly!
                    if helper.enough_disk_space_for(10):

                        # Add any pending data to the log
                        while Log.pending_data[name]:
                            log_data.append(Log.pending_data[name].pop())
                            log_data_changed = True

                            # If requested, provide confirmation that the data has been written
                            if Log.data_confirmation[name]:
                                Log.data_confirmation[name]['complete'] = True

                        # Remove any pending data from the log
                        while Log.pending_removal[name]:
                            remove_value = Log.pending_removal[name].pop()
                            log_data_changed = True

                            # Depending on the type of log, remove the data where it matches the specified value
                            if Log.simple_list[name] and isinstance(remove_value, str):
                                log_data[:] = [d for d in log_data if d != remove_value]
                            elif isinstance(remove_value, tuple):
                                log_data[:] = [d for d in log_data if d.get(remove_value[0]) != remove_value[1]]
                            else:
                                raise Exception('Invalid request to remove values from the Log')

                            # If requested, provide confirmation that the data has been removed
                            if Log.removal_confirmation[name]:
                                Log.removal_confirmation[name]['complete'] = True

                        # Apply any pending filters to clean-up data from the log
                        while Log.pending_filter[name]:
                            deleted_entries = []
                            pending_filter = Log.pending_filter[name].pop()
                            log_data_changed = True

                            # Process the log in reverse, to maintain integrity of index values as entries are removed
                            for log_entry in reversed(log_data):
                                if Log.simple_list[name]:
                                    for valid_value in pending_filter['valid_values']:
                                        # Test for a matching value *up to the length of the log entry* - extra chars
                                        # at the end of valid_value will be ignored in the match
                                        if log_entry[:len(valid_value)] == valid_value[:len(log_entry)]:
                                            break  # Valid entry - keep it
                                    else:
                                        log_data.remove(log_entry)
                                        deleted_entries.append(log_entry)
                                elif pending_filter['search_key']:
                                    for valid_value in pending_filter['valid_values']:
                                        # Test for a matching value *up to the length of the log entry* - extra chars
                                        # at the end of valid_value will be ignored in the match
                                        if (log_entry[pending_filter['search_key']][:len(valid_value)] ==
                                                valid_value[:len(log_entry[pending_filter['search_key']])]):
                                            break  # Valid entry - keep it
                                    else:
                                        log_data.remove(log_entry)
                                        deleted_entries.append(log_entry[pending_filter['search_key']])
                                else:
                                    raise Exception('Invalid request to filter values in the log')

                            # If requested, provide confirmation that the filter has been applied
                            if Log.filter_confirmation[name]:
                                Log.filter_confirmation[name]['deleted_entries'] = deleted_entries
                                Log.filter_confirmation[name]['complete'] = True

                    # Perform any requested searches, based on the type of log
                    if Log.pending_search[name]:
                        Log.pending_search[name]['result'] = False
                        if Log.simple_list[name]:
                            if Log.pending_search[name]['match_partial']:
                                # Perform simple log search, including partial matches
                                if any(Log.pending_search[name]['search_value'] in d for d in log_data):
                                    Log.pending_search[name]['result'] = True
                            else:
                                # Perform simple log search, including only full matches
                                if Log.pending_search[name]['search_value'] in log_data:
                                    Log.pending_search[name]['result'] = True
                        elif Log.pending_search[name]['search_key']:
                            if Log.pending_search[name]['match_partial']:
                                # Perform dict log search, including partial matches
                                if any(Log.pending_search[name]['search_value'] in d for d
                                       in [i[Log.pending_search[name]['search_key']] for i in log_data]):
                                    Log.pending_search[name]['result'] = True
                            else:
                                # Perform dict log search, including only full string matches
                                if (Log.pending_search[name]['search_value'] in
                                        [i[Log.pending_search[name]['search_key']] for i in log_data]):
                                    Log.pending_search[name]['result'] = True
                        else:
                            raise Exception('Invalid search of log file requested.')
                        Log.pending_search[name]['complete'] = True

                    # Perform any requested lookups, based on the type of log
                    if Log.pending_lookup[name]:
                        Log.pending_lookup[name]['result'] = []
                        if Log.simple_list[name]:
                            # Test for a matching value *up to the length of the log entry* - extra characters
                            # at the end of search_value will be ignored in the match.  For simple-type logs
                            for log_entry in log_data:
                                if log_entry == Log.pending_lookup[name]['search_value'][:len(log_entry)]:
                                    Log.pending_lookup[name]['result'] = log_entry
                                    break
                        elif Log.pending_lookup[name]['search_key']:
                            # Test for a matching value *up to the length of the log entry* - extra characters
                            # at the end of search_value will be ignored in the match.  For dict-type logs
                            for log_entry in log_data:
                                search_key = Log.pending_lookup[name]['search_key']
                                if (log_entry[search_key] ==
                                        Log.pending_lookup[name]['search_value'][:len(log_entry[search_key])]):
                                    Log.pending_lookup[name]['result'] = [log_entry[k] for k
                                                                          in Log.pending_lookup[name]['return_keys']]
                                    break
                        else:
                            raise Exception('Invalid lookup in log file requested.')
                        Log.pending_lookup[name]['complete'] = True

                    # If required_for for an aggregate_log, save this log_data into this dict so it's available below
                    if name in log_data_for_agg:
                        log_data_for_agg[name] = log_data

                    # Only re-save to file if anything has changed - if just searching then won't need to
                    if log_data_changed:
                        # Once log_data has been updated, re-sort it by timestamp (newest first)
                        if Log.simple_list[name]:
                            log_data.sort(reverse=True)
                        else:
                            log_data.sort(key=lambda k: k['timestamp'], reverse=True)

                        # Save log_data back to file
                        with open(Log.fullpaths[name], 'w') as log_handle:
                            json.dump(log_data, log_handle, indent=2, sort_keys=True)

                    # Save log data if needed for use outside
                    if Log.pending_entire_log[name]:
                        Log.pending_entire_log[name]['result'] = log_data
                        Log.pending_entire_log[name]['available'] = True

                    # Delete log_data - if no longer needed (this decrements reference count), reduces memory footprint
                    del log_data

                # If the entire log is flagged as finished, remove this specific log so we know it's up-to-date
                if Log.finished:
                    Log.names.remove(name)

            # Update the aggregate logs, if required_for
            for agg_name in Log.agg_names:
                if Log.agg_pending_update[agg_name]:
                    for name in Log.agg_logs_needed[agg_name]:
                        if name not in log_data_for_agg:
                            # If this name isn't available, then can't update this aggregate log yet - let it loop again
                            break

                    else:
                        # Only attempt to update the aggregate logs if there is sufficient disk space.
                        if helper.enough_disk_space_for(50):
                            # All required_for data was found, so continue
                            datestamp = helper.datestamp()
                            agg_data = []

                            # Load existing agg log data from file, if there is any
                            try:
                                with open(Log.agg_fullpaths[agg_name], 'r') as agg_handle:
                                    agg_data = json.load(agg_handle)
                            except (IOError, json.decoder.JSONDecodeError):
                                pass

                            # Remove any entry for current day from the aggregate file - we'll re-generate this below
                            agg_data[:] = [d for d in agg_data if d.get('date') != datestamp]

                            # Create the aggregate entry for today, with a timestamp plus fields specified in agg_spec
                            agg_today = {'date': datestamp}
                            for agg_field in Log.agg_spec[agg_name]:
                                if Log.simple_list[agg_field['source']]:
                                    log_data_today = [d for d in log_data_for_agg[agg_field['source']] if
                                                      d[:10] == datestamp]
                                else:
                                    log_data_today = [d for d in log_data_for_agg[agg_field['source']] if
                                                      d.get('timestamp')[:10] == datestamp]
                                agg_today[agg_field['name']] = agg_field['function'](log_data_today)
                                del log_data_today

                            # Add today's entry to any previous, and re-sort the list with newest first
                            agg_data.append(agg_today)
                            agg_data.sort(key=lambda k: k['date'], reverse=True)

                            # Save the aggregate log to file
                            with open(Log.agg_fullpaths[agg_name], 'w') as agg_handle:
                                json.dump(agg_data, agg_handle, indent=2, sort_keys=True)

                            # Delete agg_data if no longer needed (this decrements ref count), reduces memory footprint
                            del agg_data

                            # Mark this aggregate log update as completed
                            Log.agg_pending_update[agg_name] = False
                            if Log.agg_update_confirmation[agg_name]:
                                Log.agg_update_confirmation[agg_name]['complete'] = True

            # At the end of every loop, clear any data saved for the aggregate log to minimise memory usage
            log_data_for_agg.clear()

            # Once all logs are finished, break out of this thread
            if Log.finished and len(Log.names) == 0:
                break

            # Sleep at the end of each loop, to avoid over-processing in this thread when nothing is happening
            helper.sleep(0.02)


