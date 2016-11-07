"""
Provide support for nest thermostats.

License
=======

Feel free to use or copy under the MIT license.

The Yombo team and other contributors hopes that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
or FITNESS FOR A PARTICULAR PURPOSE.

.. moduleauthor:: Mitch Schwenk <mitch-gw@yombo.net>
:copyright: Copyright 2016 by Yombo.
"""
# Import python libraries
import treq
try:  # Prefer simplejson if installed, otherwise json will work swell.
    import simplejson as json
except ImportError:
    import json

# Import twisted libraries
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.internet.serialport import SerialPort
from twisted.internet.task import LoopingCall

from yombo.core.log import get_logger
from yombo.core.module import YomboModule
from yombo.utils import unit_converters

logger = get_logger("modules.nest")

import sys
from optparse import OptionParser

class Nest(YomboModule):
    """
    Provides support for nest. Periodically gets the status of the HVAC system.
    """
    @inlineCallbacks
    def _init_(self):
        # self.username = self._ModuleVariables['username'][0]['value']
        # self.password = self._ModuleVariables['password'][0]['value']

        self.devices = {}
        self.temp_display = self.set('misc', 'temp_display', 'f')


        devices = self._GetDevices()
        for device_id, device in devices.iteritems():
            results = yield self.nest_login(device)  # todo: convert access token storage to SQLDict for caching
            if results is not True:
                logger.warn("NEST Module is unable to get information for nest thermostat. Nest ID: {id} Reason: {reason}",
                            id=device.device_variables['nest_id'][0]['value'],
                            reason=results)
                del self.devices[device_id]

    def _module_devicetypes_(self, **kwargs):
        """
        Tell the gateway what types of devices we can handle.

        :param kwargs:
        :return:
        """
        return ['nest_thermostat']

    def _statistics_lifetimes_(self, **kwargs):
        """
        We keep 10 days of max data, 30 days of hourly data, 1 of daily data
        """
        return {'lib.atoms.#': {'full':10, '5m':30, '15m':30, '60m':0} }
        # we don't keep 6h averages.

    def _configuration_set_(self, **kwargs):
        """
        Receive configuruation updates and adjust as needed.

        :param kwargs: section, option(key), value
        :return:
        """
        section = kwargs['section']
        option = kwargs['option']
        value = kwargs['value']

        if section == 'misc':
            if option == 'temp_display':
                self.temp_display = value

    @inlineCallbacks
    def nest_login(self, device):
        username = device.device_variables['username'][0]['value']
        password = device.device_variables['password'][0]['value']

        response = yield treq.post("https://home.nest.com/user/login",
                                    {"username": username, "password": password},
                                    headers={"user-agent":"Nest/1.1.0.10 CFNetwork/548.0.4"}
                                   )

        content = yield treq.content(response)
        content = json.loads(content)  # convert from json to dictionary

        self.devices[device.device_id]['nest_serial'] = device.device_variables['nest_serial'][0]['value']
        self.devices[device.device_id]['transport'] = content['urls']['transport_url']
        self.devices[device.device_id]['access_token'] = content['access_token']
        self.devices[device.device_id]['userid'] = content['userid']
        self.devices[device.device_id]['statistics_label'] = device.device_variables['statistics_label'][0]['value']
        returnValue(True)

    @inlineCallbacks
    def get_status(self, device_id):
        transport = self.device[device_id]['transport']
        userid = self.device[device_id]['userid']
        access_token = self.device[device_id]['access_token']

        response = yield treq.get(transport + "/v2/mobile/user." + userid,
                            headers={"user-agent":"Nest/1.1.0.10 CFNetwork/548.0.4",
                                       "Authorization":"Basic " + access_token,
                                       "X-nl-user-id": userid,
                                       "X-nl-protocol-version": "1"}
                            )

        content = yield treq.content(response)
        content = json.loads(content)  # convert from json to dictionary

        # we have to map the nest serial to the structure, to get the correct structure information.
        nest_serial = self.devices[device_id]['nest_serial']
        structure_id = content['link'][nest_serial]['structure'].split('.')[0]  # structure.xxxxxx...

        shared = content['shared'][nest_serial]
        device = content['devices'][nest_serial]
        structure = content['structure'][structure_id]

        status = shared
        status.update(device)
        status.udpate(structure)

        stats_label = self.devices[device.device_id]['statistics_label']

        #lets calculate if we are off, cool 1, cool 2, cool 3, heat 1, heat 2, heat 3
        if shared['hvac_fan_state'] is True:
            fan_state = 1
        else:
            fan_state = 0

        if shared['hvac_heat_x3_state'] is True:
            fan_state = 1
            mode = 'heat 3'
        elif shared['hvac_heat_x2_state'] is True:
            fan_state = 1
            mode = 'heat 2'
        elif shared['hvac_heater_state'] is True:
            fan_state = 1
            mode = 'heat 1'
        elif shared['hvac_cool_x3_state'] is True:
            fan_state = 1
            mode = 'cool 3'
        elif shared['hvac_cool_x2_state'] is True:
            fan_state = 1
            mode = 'cool 2'
        elif shared['hvac_ac_state'] is True:
            fan_state = 1
            mode = 'cool 1'
        else:
            mode = 'off'

        self._Statistics.averages(stats_label + ".current_temp", shared['current_temperature'], bucket_time=5)
        self._Statistics.averages(stats_label + ".mode", mode, bucket_time=5)
        self._Statistics.averages(stats_label + ".fan_state", fan_state, bucket_time=5)

        self.devices[device_id]['status'] = status

    def _device_command_(self, **kwargs):
        """
        Received a request to do perform a command for a device.

        :param kwags: Contains 'device' and 'command'.
        :return: None
        """
        logger.info("X10 API received device_command: {kwargs}", kwargs=kwargs)
        device = kwargs['device']
        request_id = kwargs['request_id']
        device.command_received(request_id)
        command = kwargs['command']

        logger.info("Testing if Nest module has information for device_id: {device_id}",
                device_id=device.device_id)
        if device.device_id not in self.devices:
            logger.info("Skipping _device_command_ call since '{device_id}' isn't valide.",
                    device_id=device.device_id)
            return  # not meant for us.

    @inlineCallbacks
    def api_post(self, device_id, type, data):
        transport = self.device[device_id]['transport']
        serial = self.devices[device.device_id]['nest_serial']
        userid = self.device[device_id]['userid']
        access_token = self.device[device_id]['access_token']

        response = yield treq.get(transport + "/v2/mobile/" + type + "." + serial,
                            data,
                            headers={"user-agent":"Nest/1.1.0.10 CFNetwork/548.0.4",
                                       "Authorization":"Basic " + access_token,
                                       "X-nl-protocol-version": "1"})
        content = yield treq.content(response)
        content = json.loads(content)  # convert from json to dictionary
        returnValue(content)

    @inlineCallbacks
    def set_temp(self, device_id, temp):
        if (self.temp_display == "f"):  # nest always talks in c, so we convert any inputs if system is set to f.
            temp = unit_converters['f_c'](temp)

        request_data = '{"target_change_pending":true,"target_temperature":' + '%0.1f' % temp + '}'
        response = yield self.api_post(device_id, 'shared', request_data)

    @inlineCallbacks
    def set_fan(self, state):

        request_data = '{"fan_mode":"' + str(state) + '"}'
        response = yield self.api_post(device_id, 'device', request_data)


