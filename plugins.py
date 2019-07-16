from kd_app_thread import AppThread
import kd_timers


class TriggerZones(AppThread):

    def threaded_function(self, clip, trigger_zones):

        while True:

            if self.should_abort():
                return

            for segment in [segment for segment in clip.segments if segment.is_required_for('TRIGGER_ZONE')]:

                for frame_time in range(segment.start_time, segment.end_time, clip.time_increment):
                    for subject in clip.frames[frame_time].subjects:
                        is_triggered = subject.within_trigger_zone(trigger_zones)
                        zones = [zone for zone, triggered in is_triggered.items() if triggered]
                        for zone in zones:
                            if zone not in segment.trigger_zones:
                                segment.trigger_zones.append(zone)
                            # TODO: Break out of the loops here, if found all zones
                            # TODO: Make this more flexible, provide option to also do per individual frame - and then
                            # TODO:  use that to help make the primary composite more relevant

                    clip.remove_redundant_frame(time=frame_time,
                                                expired_requirement='TRIGGER_ZONE')

                segment.remove_requirement('TRIGGER_ZONE')

            else:
                if clip.created_all_segments:
                    break
                kd_timers.sleep(secs=0.2)


