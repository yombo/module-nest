"""
Provide suppot for NEST devices.

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
import yombo.ext.treq as treq
try:  # Prefer simplejson if installed, otherwise json will work swell.
    import simplejson as json
except ImportError:
    import json
import math
from hashlib import sha256
from dateutil import parser as duparser
import time

# Import twisted libraries
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.task import LoopingCall
from twisted.internet import reactor

from yombo.core.exceptions import YomboWarning
from yombo.core.log import get_logger
from yombo.core.module import YomboModule
from yombo.lib.webinterface.auth import require_auth
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
        self.tempurature_display = self._Configs.get2('misc', 'tempurature_display', 'f')
        self.pending_requests = {}  # track pending requests here.

        self.nest_transport = None
        self.nest_access_token = None

        self.nest_user_agent = "Nest/2.1.3 CFNetwork/548.0.4"
        self.nest_protocol_version = "1"

        self.nest_device_type = self._DeviceTypes['nest_thermostat']
        self.nest_accounts  = yield self._SQLDict.get(self, "nestaccounts")  # store transports and access tokens here.

    def _start_(self):
        """
        Sets up a period call to get nest thermostat status.

        :return:
        """
        self.period_status_loop = LoopingCall(self.period_status)
        self.period_status_loop.start(300)

    def _module_devicetypes_(self, **kwargs):
        """
        Tell the gateway what types of devices we can handle.

        :param kwargs:
        :return:
        """
        return ['nest_thermostat']

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

    def _webinterface_add_routes_(self, **kwargs):
        """
        Adds a configuration block to the web interface. This allows users to view their nest account for
        thermostat ID's which they can copy to the device setup page.
        :param kwargs:
        :return:
        """
        #        if self.loadedLibraries['atoms']['loader.operation_mode'] = val
        return {
            'nav_side': [
                {
                    'label1': 'Tools',
                    'label2': 'NEST',
                    'priority1': None,  # Even with a value, 'Tools' is already defined and will be ignored.
                    'priority2': 5000,
                    'icon': 'fa fa-thermometer-three-quarters fa-fw',
                    'url': '/tools/module_nest',
                    'tooltip': '',
                    'opmode': 'run',
                },
            ],
            'routes': [
                self.web_interface_routes,
            ],
        }

    def web_interface_routes(self, webapp):
        """
        Adds routes to the webinterface module.

        :param webapp: A pointer to the webapp, it's used to setup routes.
        :return:
        """
        with webapp.subroute("/") as webapp:
            @webapp.route("/tools/module_nest", methods=['GET'])
            @require_auth()
            @inlineCallbacks
            def page_tools_module_nest_get(webinterface, request, session):

                if 'module_nest_password' in session:
                    password = yield self._GPG.decrypt(session['module_nest_password'])
                else:
                    password = ""
                page = webinterface.webapp.templates.get_template('modules/nest/web/home.html')
                returnValue(page.render(alerts=webinterface.get_alerts(),
                                   session=session,
                                   password=password,
                                   ))

            @webapp.route('/tools/module_nest', methods=['POST'])
            @require_auth()
            @inlineCallbacks
            def page_tools_module_nest_post(webinterface, request, session):
                # print "in nest post..."

                try:
                    session['module_nest_username'] = request.args.get('username')[0]
                    password = request.args.get('password')[0]
                    session['module_nest_password'] = yield self._GPG.encrypt(request.args.get('password')[0])
                    reactor.callLater(600, self.clean_session_data, session)
                except Exception, e:
                    webinterface.add_alert('Invalid form request. Try again.', 'warning')
                    page = webinterface.webapp.templates.get_template('modules/nest/web/home.html')
                    returnValue(page.render(alerts=webinterface.get_alerts(),
                                            session=session,
                                            password=password,
                                            ))

                try:
                    results = yield self.tools_list_nest_devices(session['module_nest_username'], password)
                    # print "nest results: %s" % results
                    for i, device in enumerate(results['devices']):
                        print "i: %s" % i
                        # print "device: %s" % device
                        results['devices'][i]['json_output'] =  json.dumps({
                            'device_id': '',
                            'label': device['name'],
                            'description': device['name'],
                            'statistic_label': "myhouse." + device['location'].lower() + "." + device['name'].lower(),
                            'statistic_lifetime': 0,
                            'device_type_id': self.nest_device_type['device_type_id'],
                            'pin_code': "",
                            'pin_timeout': 0,
                            'energy_type': "electric",
                            'vars': [
                            ],
                            # 'variable_data': json_output['vars'],
                        })

                    # print "nest results: %s" % results

                except Exception, e:
                    webinterface.add_alert('Error with NEST module: %s' % e, 'warning')
                    page = webinterface.webapp.templates.get_template('modules/nest/web/home.html')
                    returnValue(page.render(alerts=webinterface.get_alerts(),
                                            session=session,
                                            password=password,
                                            ))

                if results['status'] == 'failed':
                    webinterface.add_alert('%s' % results['msg'], 'warning')
                    page = webinterface.webapp.templates.get_template('modules/nest/web/home.html')
                    returnValue(page.render(alerts=webinterface.get_alerts(),
                                            session=session,
                                            password=password,
                                            ))

                # print "nest results: %s" % results
                page = webinterface.webapp.templates.get_template(str('modules/nest/web/show_account_serials.html'))
                returnValue(page.render(alerts=webinterface.get_alerts(),
                                        results=results,
                                        nest_device_type=self.nest_device_type
                                        ))

    def clean_session_data(self, session):
        """
        Remove any items stored in the session.
        
        :param session: 
        :return: 
        """
        if 'module_nest_username' in session:
            del session['module_nest_username']
        if 'module_nest_password' in session:
            del session['module_nest_password']


    @inlineCallbacks
    def tools_list_nest_devices(self, username, password):

        try:
            nest_account = yield self.get_nest_account(username, password)
        except YomboWarning as e:
            results = {
                'status': 'failed',
                'msg': e.message,
            }
            returnValue(results)

        transport = nest_account['urls']['transport_url']
        access_token = nest_account['access_token']
        userid = nest_account['userid']

        # print "Collecting NEST thermostats..."
        response = yield treq.get(transport + "/v2/mobile/user." + userid,
                            headers={"user-agent": self.nest_user_agent,
                                       "Authorization":"Basic " + access_token,
                                       "X-nl-user-id": userid,
                                       "X-nl-protocol-version": self.nest_protocol_version}
                            )
        content = yield treq.content(response)
        content = json.loads(content)  # convert from json to dictionary

        where_ids = {}
        for item_id, item in content['where'].iteritems():
            for where in item['wheres']:
                # print "where: %s" % where
                where_ids[where['where_id']] = where['name']

        devices = []
        # print content
        shared = content['shared']
        device = content['device']
        if len(shared):
            for serial, data in shared.iteritems():
                devices.append({
                    'serial': serial,
                    'name': data['name'],
                    'location': where_ids[device[serial]['where_id']],
                    'shared': data,
                    'device': device[serial],
                })
                # print "Serial: %s     Name: %s" % (serial, data['name'])
            results = {
                'status': 'success',
                'msg': "Devices found",
                'devices': devices,
            }
        else:
            results = {
                'status': 'success',
                'msg': "No devices found in your account.",
                'devices': [],
            }
        returnValue(results)

    @inlineCallbacks
    def get_nest_account(self, username, password):
        account_hash = sha256(username+password).hexdigest()
        if account_hash in self.nest_accounts:
            if self.nest_accounts[account_hash]['expires_in_epoch'] < time.time():
                returnValue(self.nest_accounts[account_hash])
            else:
                del self.nest_accounts[account_hash]

        response = yield treq.post("https://home.nest.com/user/login",
                                   {"username": username, "password": password},
                                   headers={"user-agent": self.nest_user_agent}
                                   )

        content = yield treq.content(response)
        content = json.loads(content)  # convert from json to dictionary
        if 'error' in content:
            raise YomboWarning("Error with NEST Account: %s" % content['error_description')

        content['expires_in_epoch'] = int(duparser.parse(content['expires_in']).strftime('%s'))
        self.nest_accounts[account_hash] = content
        returnValue(content)
        # transport = content['urls']['transport_url']
        # access_token = content['access_token']
        # userid = content['userid']

    @inlineCallbacks
    def api_request(self, nest_account, method, url, data=None, headers=None):
        request_url = nest_account['urls']['transport_url'] + url
        response = yield treq.get(transport + "/v2/mobile/user." + userid,
                            headers={"user-agent": self.nest_user_agent,
                                       "Authorization":"Basic " + access_token,
                                       "X-nl-user-id": userid,
                                       "X-nl-protocol-version": self.nest_protocol_version}
                            )
        content = yield treq.content(response)
        content = json.loads(content)  # convert from json to dictionary



    @inlineCallbacks
    def period_status(self):
        """
        Periodically asks the NEST api for curent status of the device.

        :return:
        """
        for device_id, device in self.devices.iteritems():
            status = yield self.retrieve_status(device_id)
            self.save_status(device_id, status)

    @inlineCallbacks
    def retrieve_status(self, device_id):
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

        returnValue(status)

    def save_status(self, device_id, status):
        stats_label = self.devices[device_id]['statistics_label']

        #lets calculate if we are off, cool 1, cool 2, cool 3, heat 1, heat 2, heat 3
        if status['hvac_fan_state'] is True:
            fan_state = 'on'
            fan_state_value = 1
        else:
            fan_state = 'Off'
            fan_state_value = 0

        if status['hvac_heat_x3_state'] is True:
            fan_state = 'On'
            fan_state_value = 1
            run_mode = 'Heat stage 3'
            run_mode_value = 3
        elif status['hvac_heat_x2_state'] is True:
            fan_state = 'On'
            fan_state_value = 1
            run_mode = 'Heat stage 2'
            run_mode_value = 2
        elif status['hvac_heater_state'] is True:
            fan_state = 'On'
            fan_state_value = 1
            run_mode = 'Heat stage 1'
            run_mode_value = 1
        elif status['hvac_cool_x3_state'] is True:
            fan_state = 'On'
            fan_state_value = 1
            run_mode = 'Cool stage 3'
            run_mode_value = -3
        elif status['hvac_cool_x2_state'] is True:
            fan_state = 'On'
            fan_state_value = 1
            run_mode = 'Cool stage 2'
            run_mode_value = -2
        elif status['hvac_ac_state'] is True:
            fan_state = 'On'
            fan_state_value = 1
            run_mode = 'Cool stage 1'
            run_mode_value = -1
        else:
            run_mode = 'Off'
            run_mode_value = 0

        self.device[device_id]['status']['y_fan_state'] = fan_state
        self.device[device_id]['status']['y_run_mode'] = run_mode

        # Save statistics for long term.
        self._Statistics.averages(stats_label + ".set_temperature", status['target_temperature'], bucket_time=5)
        self._Statistics.averages(stats_label + ".current_temp", status['current_temperature'], bucket_time=5)
        self._Statistics.averages(stats_label + ".current_humidity", status['current_humidity'], bucket_time=5)
        self._Statistics.datapoint(stats_label + ".run_mode", run_mode_value)
        self._Statistics.datapoint(stats_label + ".fan_state", fan_state)  # on, off
        self._Statistics.datapoint(stats_label + ".mode", status['target_temperature_type'])  # cool, heat, off

        if self.tempurature_display() == 'f':
            set_temp = unit_converters['c_f'](status['target_temperature_type'])
        else:
            set_temp = status['target_temperature_type']

        device_status = {
            'human_status': _('module.nest',"Thermostat is set to {mode}, is set to {set_temp}{temp_scale}, and is currently {state}. The fan is {fan_state}.".format(
                mode=_('common', status['target_temperature_type'].title()),
                set_temp=_('common', set_temp),
                temp_scale=_('common.temperatures', set_temp),
                state=_('common', run_mode.title()),
                fan_state=_('common', fan_state)
            )),
            'machine_status': run_mode_value,
            'machine_status_extra': {
                                    'mode': status['target_temperature_type'],
                                    'current_temperature': status['current_temperature'],
                                    'fan_state': fan_state_value,
                                    'set_temperature': status['target_temperature'],
                                    'current_humidity': status['current_humidity'],
            },
            'source': self,
        }

        self.device[device_id].set_status(**device_status)  # set and send the status of the thermostat

        # Tell the rest of the system about the current state of a particular thermostat
        starter = 'thermostat.%s.' % self.devices[device_id]['nest_number']
        self._States.set(starter + "features", ['humidity', 'temperature', 'set_temperature', 'fan_state', 'run_mode'])
        self._States.set(starter + "humidity", status['current_humidity'])
        self._States.set(starter + "set_temperature", status['target_temperature'])
        self._States.set(starter + "temperature", status['current_temperature'])
        self._States.set(starter + "run_mode", run_mode_value)
        self._States.set(starter + "fan_state", fan_state)

        # This is a litle complex because there could be multiple nest thermostats. We average them together
        humidities = []
        temps = []
        set_temps = []
        run_modes = []
        fan_states = []

        for device_id, data in self.devices.iteritems():
            status = self.device[device_id]['status']
            temps.append(status['current_temperature'])
            set_temps.append(status['target_temperature'])
            humidities.append(status['current_humidity'])
            run_modes.append(status['y_run_mode'])
            fan_states.append(status['y_fan_state'])

        count = len(self.devices)

        calc = sum(humidities) / float(count)
        avg_humidity = math.ceil(calc) if calc > 0 else math.floor(calc)
        calc = sum(temps) / float(count)
        avg_temp = math.ceil(calc) if calc > 0 else math.floor(calc)
        calc = sum(set_temps) / float(count)
        avg_set_temp = math.ceil(calc) if calc > 0 else math.floor(calc)
        calc = sum(run_modes) / float(count)
        avg_run_mode = math.ceil(calc) if calc > 0 else math.floor(calc)
        calc = sum(fan_states) / float(count)
        avg_fan_state = math.ceil(calc) if calc > 0 else math.floor(calc)

        master = self.devices[device_id]['master']
        # Tell the rest of the system about the curent averages.
        self._States.set("thermostat.average.features", ['humidity', 'temperature', 'set_temperature', 'fan_state', 'run_mode'])
        self._States.set("thermostat.average.humidity", avg_humidity)
        self._States.set("thermostat.average.set_temperature", avg_set_temp)
        self._States.set("thermostat.average.temperature", avg_temp)
        self._States.set("thermostat.average.run_mode", avg_run_mode)
        self._States.set("thermostat.average.fan_state", avg_fan_state)

    def device_command_send_pending(self, request_id):
        self.pending_requests[request_id]['device'].device_command_pending(request_id)
        self.pending_requests[request_id]['nest_pending_callback'] = \
            reactor.callLater(15, self.device_command_cancel, request_id)

    def device_command_cancel(self, request_id):
        if self.pending_requests[request_id]['nest_pending_callback'].active():
            self.pending_requests[request_id]['nest_pending_callback'].cancel()

        self.pending_requests[request_id]['device'].device_command_failed(request_id,
            message=_('module.nest', 'NEST timed out, check network connection.'))
        self.pending_requests[request_id]['nest_running'] = False

    @inlineCallbacks
    def _device_command_(self, **kwargs):
        """
        Received a request to do perform a command for a device.

        :param kwags: Contains 'device' and 'command'.
        :return: None
        """
        logger.info("NEST received device_command: {kwargs}", kwargs=kwargs)
        device = kwargs['device']
        request_id = kwargs['request_id']
        self.pending_requests[request_id] = kwargs
        self.pending_requests[request_id]['nest_running'] = True

        command = kwargs['command']

        logger.info("Testing if Nest module has information for device_id: {device_id}",
                device_id=device.device_id)
        if device.device_id not in self.devices:
            logger.info("Skipping _device_command_ call since '{device_id}' isn't valid.",
                    device_id=device.device_id)
            returnValue()  # not meant for us.

        device.device_command_received(request_id, message=_('module.nest', 'Handled by NEST module.'))
        self.pending_requests[request_id]['nest_pending_callback'] = \
            reactor.callLater(1, self.device_command_send_pending, request_id)

        results = {}
        if command.machine_label in ('cool', 'heat', 'off'):
            device.command_pending(request_id)
            results = yield self.set_mode(device.device_id, command.machine_label, request_id)
        elif command.machine_label == 'set_temp':
            if 'target_temp' not in kwargs:
                logger.warn("NEST Requires 'target_temp' in kwargs of do_command request.")
                self.device_command_cancel(request_id)
            else:
                device.command_pending(request_id)
                results = yield self.set_temp(device.device_id, kwargs['target_temp'], request_id)
        else:
            logger.warn("NEST received unknown command: {command}", command=command.machine_label)
            self.device_command_cancel(request_id)

        if self.pending_requests[request_id]['nest_running'] is True:
            status = yield self.retrieve_status(device.device_id)

        if self.pending_requests[request_id]['nest_running'] is True:
            if status is not False:
                self.save_status(device.device_id, status)
                device.command_done(request_id)
            else:
                device.command_failed(request_id, message=_('module.nest', "NEST timed out, check network connection."))

        if self.pending_requests[request_id]['nest_pending_callback'].active():
            self.pending_requests[request_id]['nest_pending_callback'].cancel()
        del self.pending_requests[request_id]

    @inlineCallbacks
    def api_post(self, device_id, type, data):
        transport = self.device[device_id]['transport']
        serial = self.devices[device_id]['nest_serial']
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
        response = yield self.api_post(device_id, 'shared')

    @inlineCallbacks
    def set_fan(self, device_id, state):

        request_data = '{"fan_mode":"' + str(state) + '"}'
        response = yield self.api_post(device_id, 'device', request_data)

    @inlineCallbacks
    def set_mode(self, device_id, state):

        request_data = '{"target_temperature_type":"' + str(state) + '"}'
        response = yield self.api_post(device_id, 'shared', request_data)

