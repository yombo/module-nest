NEST Thermostats
================

This module provides support for interacting with NEST thermostats.

Installation
============

Simply mark this module as being used by the gateway, and the gateway will
download this module and install this module automatically.

Requirements
============

None

Usage
=====

Included is a pthon script to collect the available NEST thermostat serial
numbers for a given account. This serial number is required so that Yombo
can properly manage the device.  To use:

cd yombo-gateway/yombo/modules/nest/
./lookup.py emailsaddress@example.com MyPasswordHere

Copy the desired serial number into the device configuration within Yombo.

License
=======

Feel free to use or copy under the MIT license. See the
`MIT License <hhttps://opensource.org/licenses/MIT>`_ for more details.

The **`Yombo <https://yombo.net/>`_** team and other contributors
hopes that it will be useful, but WITHOUT ANY WARRANTY; without even the
implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.


