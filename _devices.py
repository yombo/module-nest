from yombo.lib.devices.climate import Climate

from yombo.core.exceptions import YomboWarning
from yombo.utils import unit_converters

STATUS_HOLDS_AUTO_AWAY = 'auto_away'

class NEST_Thermostat(Climate):
    """
    A generic light device.
    """

    SUB_PLATFORM = "nest"

    current_mode_map = {
        'COOL': 'cool',
        'HEAT': 'heat',
        'OFF': 'off',
    }

    def _init_(self):
        self.add_status_extra_any(('name'))

    def _start_(self):
        self._fan_list = ['on', 'auto']
        self.__device = None  # will be filled with data from the NEST API.

    @property
    def device(self):
        return self.__device

    @device.setter
    def device(self, val):
        self.__device = val
        self.update_status()

    def update_status(self):
        """
        Should be called whenever we get new device status update.
        :return: 
        """
        status = self.__device['status']
        shared = self.__device['shared']
        structure = self.__device['structure']

        status_extra = {}

        self._away = self.structure.away == 'away'


        # lets calculate if we are off, cool 1, cool 2, cool 3, heat 1, heat 2, heat 3
        if status['hvac_fan_state'] is True:
            status_extra['fan'] = 'fan_only'
        else:
            status_extra['fan'] = 'off'

        if status['hvac_heater_state'] is True:
            status_extra['fan'] = 'on'
            status_extra['running'] = 'heat'
        elif status['hvac_heat_x2_state'] is True:
            status_extra['fan'] = 'on'
            status_extra['running'] = 'heat2'
        elif status['hvac_heat_x3_state'] is True:
            status_extra['fan'] = 'on'
            status_extra['running'] = 'heat3'
        elif status['hvac_ac_state'] is True:
            status_extra['fan'] = 'on'
            status_extra['running'] = 'cool'
        elif status['hvac_cool_x2_state'] is True:
            status_extra['fan'] = 'on'
            status_extra['running'] = 'cool2'
        elif status['hvac_cool_x3_state'] is True:
            status_extra['fan'] = 'on'
            status_extra['running'] = 'cool3'
        else:
            status_extra['fan'] = 'off'
            status_extra['running'] = 'off'

        status_extra['mode'] = self.current_mode_map[status['current_schedule_mode']]

        if structure['away'] == False:
            status_extra['hold'] = 'away'
        else:
            status_extra['hold'] = 'home'

        status_extra['humidity'] = float(status['current_humidity'])
        status_extra['temperature'] = float(status['current_temperature'])
        machine_status = float(shared['current_temperature'])
        status_extra['target_temp'] = float(shared['target_temperature'])
        status_extra['target_temp_high'] = float(shared['target_temperature_high'])
        status_extra['target_temp_low'] = float(shared['target_temperature_low'])
        status_extra['name'] = shared['name']

        # Save statistics for long term.
        statistic_label = self.statistic_label
        if statistic_label is not None:
            self._Statistics.averages("%s.%s" (statistic_label, 'temperature'), status_extra['temperature'], bucket_time=5)
            self._Statistics.averages("%s.%s" (statistic_label, 'humidity'), status_extra['humidity'], bucket_time=5)
            self._Statistics.averages("%s.%s" (statistic_label, 'fan'), status_extra['fan'], bucket_time=5)
            self._Statistics.averages("%s.%s" (statistic_label, 'running'), status_extra['running'], bucket_time=5)
            self._Statistics.averages("%s.%s" (statistic_label, 'hold'), status_extra['hold'], bucket_time=5)
            self._Statistics.averages("%s.%s" (statistic_label, 'mode'), status_extra['mode'], bucket_time=5)
            self._Statistics.averages("%s.%s" (statistic_label, 'target_temp_low'), status_extra['target_temp_low'], bucket_time=5)
            self._Statistics.averages("%s.%s" (statistic_label, 'target_temp_high'), status_extra['target_temp_high'], bucket_time=5)

        if self.temperature_display() == 'f':
            set_temp = unit_converters['c_f'](status['target_temperature_type'])
        else:
            set_temp = status['target_temperature_type']

        device_status = {
            'human_status': _(
                'module.nest',
                 "Thermostat is set to {mode}, is set to {set_temp}{temp_scale}, and is currently {state}. The fan is {fan_state}.".format(
                      mode=_('common', status_extra['mode'].title()),
                      set_temp=_('common', status_extra['target_temp_low']),
                      temp_scale=_('common.temperatures', status_extra['target_temp_low']),
                      state=_('common', status_extra['running'].title()),
                      fan_state=_('common', status_extra['fan'])
                 )),
            'machine_status': machine_status,
            'machine_status_extra': status_extra,
            'source': self,
        }

        self.set_status(**device_status)  # set and send the status of the thermostat

        # Tell the rest of the system about the current state of a particular thermostat
        starter = 'thermostat.%s.' % self.machine_label
        self._States.set(starter + "target_temperature", status_extra['target_temp'])
        self._States.set(starter + "current_temperature", status_extra['temperature'])
        self._States.set(starter + "humidity", status_extra['humidity'])
        self._States.set(starter + "run_mode", status_extra['mode'])
        self._States.set(starter + "fan_state", status_extra['fan'])

        # # This is a litle complex because there could be multiple nest thermostats. We average them together
        # humidities = []
        # temps = []
        # set_temps = []
        # run_modes = []
        # fan_states = []
        #
        # for device_id, data in self.devices.items():
        #     status = self.device[device_id]['status']
        #     temps.append(status['current_temperature'])
        #     set_temps.append(status['target_temperature'])
        #     humidities.append(status['current_humidity'])
        #     run_modes.append(status['y_run_mode'])
        #     fan_states.append(status['y_fan_state'])
        #
        # count = len(self.devices)
        #
        # calc = sum(humidities) / float(count)
        # avg_humidity = math.ceil(calc) if calc > 0 else math.floor(calc)
        # calc = sum(temps) / float(count)
        # avg_temp = math.ceil(calc) if calc > 0 else math.floor(calc)
        # calc = sum(set_temps) / float(count)
        # avg_set_temp = math.ceil(calc) if calc > 0 else math.floor(calc)
        # calc = sum(run_modes) / float(count)
        # avg_run_mode = math.ceil(calc) if calc > 0 else math.floor(calc)
        # calc = sum(fan_states) / float(count)
        # avg_fan_state = math.ceil(calc) if calc > 0 else math.floor(calc)
        #
        # master = self.devices[device_id]['master']
        # # Tell the rest of the system about the curent averages.
        # self._States.set("thermostat.average.features",
        #                  ['humidity', 'temperature', 'set_temperature', 'fan_state', 'run_mode'])
        # self._States.set("thermostat.average.humidity", avg_humidity)
        # self._States.set("thermostat.average.set_temperature", avg_set_temp)
        # self._States.set("thermostat.average.temperature", avg_temp)
        # self._States.set("thermostat.average.run_mode", avg_run_mode)
        # self._States.set("thermostat.average.fan_state", avg_fan_state)
