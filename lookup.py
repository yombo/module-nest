#! /usr/bin/python
"""
Looks up NEST serial numbers for inputting into the device configuration section within Yombo.

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
try:  # Prefer simplejson if installed, otherwise json will work swell.
    import simplejson as json
except ImportError:
    import json
import treq
from optparse import OptionParser

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.task import react

@inlineCallbacks
def show_serials(username, password):

    print "Logging into nest..."
    response = yield treq.post("https://home.nest.com/user/login",
                                {"username": username, "password": password},
                                headers={"user-agent":"Nest/1.1.0.10 CFNetwork/548.0.4"}
                               )
    content = yield treq.content(response)

    content = json.loads(content)  # convert from json to dictionary

    transport = content['urls']['transport_url']
    access_token = content['access_token']
    userid = content['userid']

    print "Collecting NEST thermostats..."
    response = yield treq.get(transport + "/v2/mobile/user." + userid,
                        headers={"user-agent":"Nest/1.1.0.10 CFNetwork/548.0.4",
                                   "Authorization":"Basic " + access_token,
                                   "X-nl-user-id": userid,
                                   "X-nl-protocol-version": "1"}
                        )
    content = yield treq.content(response)
    content = json.loads(content)  # convert from json to dictionary

    shared = content['shared']
    print "\nEnter this desired serial string into the device configuration:"
    if len(shared):
        for serial, data in shared.iteritems():
            print "Serial: %s     Name: %s" % (serial, data['name'])
    else:
        print "No devices found."

    print "\nEnd of line\n"

def command_parser():
   parser = OptionParser(usage="lookup.py username password",
        description="Looks serial numbers for a user's account.",
        version="1.0")
   return parser

def help():
    print "syntax: list.py username password"
    print
    print "examples:"
    print "    list.py joe@user.com swordfish"

@inlineCallbacks
def main(reactor, *args):
    parser = command_parser()
    (opts, args) = parser.parse_args()

    if (len(args)<2) or (args[0]=="help"):
        help()
        reactor.stop()

    username = args[0]
    password = args[1]

    print "\nThis program outputs available NEST thermostats for your account.\n"
    # n = Nest(username, password)
    yield show_serials(username, password)

if __name__=="__main__":
   react(main, [])
