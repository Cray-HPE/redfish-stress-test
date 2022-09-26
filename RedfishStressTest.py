# MIT License
#
# (C) Copyright [2022] Hewlett Packard Enterprise Development LP
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

# pylint: disable=line-too-long
# pylint: disable=invalid-name
# pylint: disable=global-statement
# pylint: disable=missing-docstring
# pylint: disable=broad-except
# pylint: disable=too-many-nested-blocks
# pylint: disable=too-many-locals
# pylint: disable=too-many-boolean-expressions
# pylint: disable=too-many-statements
# pylint: disable=too-many-return-statements
# pylint: disable=too-many-branches

from datetime import datetime
from http import HTTPStatus
from urllib.parse import urlparse

import os
import sys
import argparse
import logging
import json
import time
import requests
import urllib3

from requests.auth import HTTPBasicAuth

TOOL_VERSION = '1.0.0'

my_logger = logging.getLogger()
my_logger.setLevel(logging.DEBUG)
standard_out = logging.StreamHandler(sys.stdout)
standard_out.setLevel(logging.INFO)
my_logger.addHandler(standard_out)
standard_err = logging.StreamHandler(sys.stderr)
standard_err.setLevel(logging.ERROR)
my_logger.addHandler(standard_err)

VERBOSE1 = logging.INFO - 1
VERBOSE2 = logging.INFO - 2
logging.addLevelName(VERBOSE1, "VERBOSE1")
logging.addLevelName(VERBOSE2, "VERBOSE2")

SECONDS_PER_MINUTE = 60

rate = 0
final_rate = 0
max_call = 0.0
min_call = 9999.0
avg_call = 0.0
failures = 0
max_call_url = ""
min_call_url = ""


def doCall(args, url):
    global rate
    global max_call
    global min_call
    global max_call_url
    global min_call_url
    # Until certificates or sessions are being used to talk to Redfish
    # endpoints the basic auth method will be used. To do so, SSL verification
    # needs to be turned off which results in a InsecureRequestWarning. The
    # following line disables only the IsnsecureRequestWarning.
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    auth = HTTPBasicAuth(args.username, args.password)
    headers = {
        'cache-control': 'no-cache',
    }

    url = args.ip + url
    rate = rate + 1
    start_call = time.time()

    try:
        rsp = requests.get(url=url, headers=headers, auth=auth, verify=False)

    except Exception as e:
        my_logger.log(VERBOSE1, 'Exception caught in doCall')
        my_logger.error('Unable to get URL %s %s', url, repr(e))
        end_call = time.time()
        call_time = end_call - start_call
        return call_time, None

    end_call = time.time()
    call_time = end_call - start_call

    if rsp.status_code == HTTPStatus.UNAUTHORIZED:
        my_logger.error("Authentication error trying to get URL %s", url)
        return call_time, None

    if rsp.status_code >= HTTPStatus.MULTIPLE_CHOICES:
        my_logger.error("Error requesting URL %s: %s", url, HTTPStatus(rsp.status_code))
        return call_time, None

    if call_time > max_call:
        max_call = call_time
        max_call_url = url

    if call_time < min_call:
        min_call = call_time
        min_call_url = url

    return call_time, rsp


BMC_FW_NAMES = ['BMC', 'iLO 5']


def getFirmwareVersion(args):
    _, service_root = doGenericURICall(args, "/redfish/v1/", "Service Root")
    if service_root is not None:
        _, update_service = doGenericURICall(args, service_root["UpdateService"]['@odata.id'], "UpdateService")
        if update_service is not None:
            _, firmware_inventory = doGenericURICall(args, update_service["FirmwareInventory"]['@odata.id'], "FirmwareInventory")
            if firmware_inventory is not None:
                for m in firmware_inventory['Members']:
                    _, firmware_entry = doGenericURICall(args, m['@odata.id'], "firmware entry")
                    if firmware_entry is not None:
                        if firmware_entry['Name'] in BMC_FW_NAMES:
                            return firmware_entry['Version']
                    else:
                        my_logger.error('Failed to get firmware entry')
                my_logger.error('Could not find BMC entry in the FirmwareInventory')
            else:
                my_logger.error('Failed to get FirmwareInventory')
        else:
            my_logger.error('Failed to get UpdateService')
    else:
        my_logger.error('Failed to get service root')

    return "unknown"


def doRequests(args, rpm, runtime):
    global max_call
    global min_call
    global avg_call
    global final_rate
    global rate
    global failures

    rate = 0
    avg_arr = []
    max_call = 0
    min_call = 9999
    sleeptime = SECONDS_PER_MINUTE / rpm

    runsecs = runtime * SECONDS_PER_MINUTE

    my_logger.log(VERBOSE2, 'doRequests: sleeptime: %.2f runtime in seconds: %d', sleeptime, runsecs)

    url = prepareSystemsCall(args)
    if url is None:
        return 1

    start_requests = last_request = time.time()
    total_time = 0

    while total_time < runsecs and rate < (rpm * runtime):
        call_time, rsp = doCall(args, url)
        last_request = time.time()

        if rsp is None:
            failures = failures + 1
            my_logger.error('Poll request to %s failed', url)

        avg_arr.append(call_time)

        total_time = last_request - start_requests
        my_logger.log(VERBOSE2, 'doRequests: call %d: call_time: %.2f time accumulated: %.2f', rate, call_time, total_time)

        if call_time < sleeptime:
            time.sleep(sleeptime - call_time)

    avg_call = sum(avg_arr) / len(avg_arr)
    final_rate = rate / (total_time / SECONDS_PER_MINUTE)
    my_logger.log(VERBOSE1, 'doRequests: took: %.2f s', total_time)
    return 0


def prepareSystemsCall(args):
    # Until certificates or sessions are being used to talk to Redfish endpoints
    # the basic auth method will be used. To do so, SSL verification needs to be
    # turned off which results in a InsecureRequestWarning. The following line
    # disables only the IsnsecureRequestWarning.
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    full_url = args.ip + '/redfish/v1/Systems'
    auth = HTTPBasicAuth(args.username, args.password)
    headers = {
        'cache-control': 'no-cache',
    }

    try:
        rsp = requests.get(url=full_url, headers=headers, auth=auth, verify=False)

    except Exception as e:
        my_logger.log(VERBOSE1, 'Exception caught in %s trying to determine systems member', prepareSystemsCall.__name__)
        my_logger.error('Unable to determine systems member URI from %s: %s', full_url, repr(e))
        return None

    if rsp.status_code == HTTPStatus.UNAUTHORIZED:
        my_logger.error("Authentication error trying to call URL %s", full_url)
        return None

    if rsp.status_code >= HTTPStatus.MULTIPLE_CHOICES:
        my_logger.error("Error requesting URL %s: %s", full_url, HTTPStatus(rsp.status_code))
        return None

    data = rsp.text

    try:
        systems = json.loads(data)

    except Exception as je:
        my_logger.log(VERBOSE1, 'Exception caught in %s unmarshalling response', prepareSystemsCall.__name__)
        my_logger.error('Unable to unmarshal json response %s: %s', data, repr(je))
        return None

    if len(systems['Members']) < 1:
        my_logger.error('No systems Members found at %s', full_url)
        return None

    url = None
    if "Members" in systems:
        url = systems['Members'][0]['@odata.id']
        full_url = args.ip + url
        rsp = requests.get(url=full_url, headers=headers, auth=auth, verify=False)
        if rsp.status_code == HTTPStatus.OK:
            my_logger.info("Using %s for requests", url)

    if url is None:
        my_logger.error('Could not find a systems URL to poll')

    return url


def addStorage(uriList, payload):
    count = 0
    my_logger.log(VERBOSE1, "addStorage for %s", payload['Name'])
    if "Drives" in payload:
        for d in payload['Drives']:
            my_logger.log(VERBOSE2, "addStorage adding Drive URI %s", d['@odata.id'])
            uriList.append((payload['Name'], d['@odata.id']))
            count = count + 1

    if count < 1:
        my_logger.error("Drives list missing from %s", payload['@odata.id'])


def addComputerSystem(uriList, payload):
    global failures
    entries = ["EthernetInterfaces", "Processors", "Memory"]
    optional = ["NetworkInterfaces", "ResetActionInfo", "Storage"]
    my_logger.log(VERBOSE1, "addComputerSystem for %s", payload['@odata.id'])

    for e in entries:
        if e in payload:
            my_logger.log(VERBOSE2, "addComputerSystem adding %s URI %s", e, payload[e]['@odata.id'])
            uriList.append((e, payload[e]['@odata.id']))
        else:
            my_logger.error("Systems schema %s missing %s", payload['@odata.id'], e)
            failures = failures + 1

    for o in optional:
        if o in payload:
            my_logger.log(VERBOSE2, "addComputerSystem adding %s URI %s", o, payload[o]['@odata.id'])
            uriList.append((o, payload[o]['@odata.id']))
        else:
            my_logger.log(VERBOSE1, "Systems schema does not have optional %s", o)


def addManager(uriList, payload):
    global failures
    entries = ["EthernetInterfaces"]
    my_logger.log(VERBOSE1, "addManager for %s", payload['@odata.id'])

    for e in entries:
        if e in payload:
            my_logger.log(VERBOSE2, "addManager adding %s URI %s", e, payload[e]['@odata.id'])
            uriList.append((e, payload[e]['@odata.id']))
        else:
            my_logger.log(VERBOSE1, "Managers schema does not have optional %s", e)


def addChassis(uriList, payload):
    global failures
    entries = ["Power", "NetworkAdapters"]
    optional = ["Controls", "Assembly"]
    my_logger.log(VERBOSE1, "addChassis for %s", payload['@odata.id'])


    for e in entries:
        if e in payload:
            my_logger.log(VERBOSE2, "addChassis adding %s URI %s", e, payload[e]['@odata.id'])
            uriList.append((e, payload[e]['@odata.id']))
        else:
            my_logger.error("Chassis schema %s missing %s", payload['@odata.id'], e)
            failures = failures + 1

    for o in optional:
        if o in payload:
            my_logger.log(VERBOSE2, "addChassis adding %s URI %s", o, payload[o]['@odata.id'])
            uriList.append((o, payload[o]['@odata.id']))
        else:
            my_logger.log(VERBOSE1, "Chassis schema does not have optional %s", o)

    if ("Oem" in payload
        and "Hpe" in payload['Oem']
        and "Links" in payload['Oem']['Hpe']
        and "Devices" in payload['Oem']['Hpe']['Links']):
        my_logger.log(VERBOSE2, "addChassis adding HPE OEM Devices URI")
        uriList.append(("Chassis Devices", payload['Oem']['Hpe']['Links']['Devices']['@odata.id']))
    else:
        my_logger.log(VERBOSE1, "Chassis schema does not have optional Oem Devices")


def addCollection(uriList, payload):
    global failures
    count = 0
    my_logger.log(VERBOSE1, "addCollection for %s", payload['Name'])
    if "Members" in payload:
        for m in payload['Members']:
            my_logger.log(VERBOSE2, "addCollection adding Memeber URI %s", m['@odata.id'])
            uriList.append((payload['Name'], m['@odata.id']))
            count = count + 1

    if count < 1:
        if payload['@odata.type'].split('.')[0] == "#StorageCollection":
            my_logger.log(VERBOSE1, "StorageCollection does not have option Member list")
        else:
            my_logger.error("Member list missing from %s", payload['@odata.id'])
            failures = failures + 1


def addServiceRoot(uriList, payload):
    entries = [ "AccountService", "SessionService", "EventService", "Tasks", "UpdateService", "Chassis", "Managers", "Systems"]
    my_logger.log(VERBOSE1, "addServiceRoot for %s", payload['Name'])
    for e in entries:
        if e in payload:
            my_logger.log(VERBOSE2, "addServiceRoot adding %s URI %s", e, payload[e]['@odata.id'])
            uriList.append((e, payload[e]['@odata.id']))
        else:
            my_logger.error("Service root missing %s", e)


def doGenericURICall(args, url, label):
    my_logger.log(VERBOSE2, "doGenericURICall for %s at %s", label, url)
    call_time, rsp = doCall(args, url)

    if rsp is None:
        global failures
        failures = failures + 1
        return call_time, None

    data = rsp.text

    try:
        payload = json.loads(data)

    except Exception as je:
        my_logger.log(VERBOSE1, 'Exception caught unmarshalling %s response', label)
        my_logger.error('Unable to unmarshal json response %s: %s', data, repr(je))
        failures = failures + 1
        return call_time, None

    return call_time, payload


def doRFWalk(args, count, runtime):
    global max_call
    global min_call
    global max_call_url
    global min_call_url
    global avg_call
    global final_rate
    global rate

    LABEL = 0
    URL = 1

    rate = 0
    max_call = 0
    min_call = 9999
    max_call_url = ""
    min_call_url = ""
    avg_arr = []
    walk_count = 0

    runsecs = runtime * SECONDS_PER_MINUTE
    my_logger.log(VERBOSE2, 'walk count: %d, runtime in seconds: %d', count, runsecs)

    start_time = cur_time = time.time()

    while (cur_time - start_time) < runsecs and walk_count < count:
        uriList = []
        walk_count = walk_count + 1
        ###################################################################
        # Service Root
        ###################################################################
        call_time, service_root = doGenericURICall(args, "/redfish/v1/", "Service Root")
        cur_time = time.time()
        avg_arr.append(call_time)

        if (cur_time - start_time) > runsecs:
            my_logger.info("Reached max time during iteration %d while getting the service root", walk_count)
            break

        if service_root is None:
            my_logger.error('Failed to get service root')

        addServiceRoot(uriList, service_root)

        ###################################################################
        # Dig down making URI calls and adding additional targets
        ###################################################################
        for uri in uriList:
            my_logger.log(VERBOSE2, "Handling uri %s", str(uri))
            call_time, payload = doGenericURICall(args, uri[URL], uri[LABEL])
            cur_time = time.time()
            avg_arr.append(call_time)

            if (cur_time - start_time) > runsecs:
                my_logger.info("Reached max time during iteration %d while getting %s", walk_count, uri[LABEL])
                break

            if payload is None:
                my_logger.error('No payload for %s', uri[LABEL])
            elif "@odata.type" in payload:
                if (payload['@odata.type'] == "#ChassisCollection.ChassisCollection"
                    or payload['@odata.type'] == "#ControlsCollection.ControlsCollection"
                    or payload['@odata.type'] == "#ComputerSystemCollection.ComputerSystemCollection"
                    or payload['@odata.type'] == "#ManagerCollection.ManagerCollection"
                    or payload['@odata.type'] == "#HpeServerDeviceCollection.HpeServerDeviceCollection"
                    or payload['@odata.type'] == "#EthernetInterfaceCollection.EthernetInterfaceCollection"
                    or payload['@odata.type'] == "#NetworkInterfaceCollection.NetworkInterfaceCollection"
                    or payload['@odata.type'] == "#ProcessorCollection.ProcessorCollection"
                    or payload['@odata.type'] == "#MemoryCollection.MemoryCollection"
                    or payload['@odata.type'] == "#StorageCollection.StorageCollection"):
                    addCollection(uriList, payload)
                elif payload['@odata.type'].split('.')[0] == "#Chassis":
                    addChassis(uriList, payload)
                elif payload['@odata.type'].split('.')[0] == "#ComputerSystem":
                    addComputerSystem(uriList, payload)
                elif payload['@odata.type'].split('.')[0] == "#Manager":
                    addManager(uriList, payload)
                elif payload['@odata.type'].split('.')[0] == "#Storage":
                    addStorage(uriList, payload)
                else:
                    my_logger.log(VERBOSE2, "No match for @odata.type %s for %s", payload['@odata.type'], str(uri))

    avg_call = sum(avg_arr) / len(avg_arr)
    total_time = cur_time - start_time
    final_rate = rate / (total_time / SECONDS_PER_MINUTE)
    my_logger.log(VERBOSE1, 'doRFWalk made %d calls over %.2f s', rate, total_time)
    return 0


def main(argslist=None, configfile=None):
    """Main command

    Args:
        argslist ([type], optional): List of arguments in the form of argv. Defaults to None.
    """
    global final_rate
    global max_call
    global min_call
    global max_call_url
    global min_call_url
    global avg_call

    parser = argparse.ArgumentParser(description='HPE tool to stress test a Redfish implementation, version {}'.format(TOOL_VERSION))

    # base tool
    parser.add_argument('-v', '--verbose', action='count', default=0, help='Verbosity of tool in stdout')
    parser.add_argument('-c', '--config', type=str, help='Configuration for this tool')

    # host info
    parser.add_argument('-i', '--ip', type=str, help='Address of host to test against, using http or https (example: https://123.45.6.7:8000)')
    parser.add_argument('-u', '--username', type=str, help='Username for Authentication')
    parser.add_argument('-p', '--password', type=str, help='Password for Authentication')
    parser.add_argument('--description', type=str, help='sysdescription for identifying logs, if none is given, draw from service root')

    parser.add_argument('--logdir', type=str, default='./logs', help='directory for log files')
    parser.add_argument('--debugging', action="store_true", help='Output debug statements to text log, otherwise it only uses INFO')

    # Stress test options
    parser.add_argument('--test_requests', action='store_true', help='Execute the requests test.')
    parser.add_argument('--requests_per_minute', type=int, default=30, help='Number of sustained telemetry requests per minute. Default 30.')
    parser.add_argument('--runtime', type=int, default=1, help='Length of time to run stress test. Default 1 minute')
    parser.add_argument('--test_rf_walk', action='store_true', help='Walk the Redfish tree from the root')
    parser.add_argument('--walk_count', type=int, default=1, help='Number of times to walk the Redfish tree. Default 1')

    args = parser.parse_args(argslist)

    if configfile is None:
        configfile = args.config

    startTick = datetime.now()

    # set logging file
    standard_out.setLevel(logging.INFO - args.verbose if args.verbose < 3 else logging.DEBUG)

    logpath = args.logdir

    if not os.path.isdir(logpath):
        os.makedirs(logpath)

    fmt = logging.Formatter('%(levelname)s - %(message)s')
    file_handler = logging.FileHandler(datetime.strftime(startTick, os.path.join(logpath, "StressTest_%m_%d_%Y_%H%M%S.txt")))
    file_handler.setLevel(min(logging.INFO if not args.debugging else logging.DEBUG, standard_out.level))
    file_handler.setFormatter(fmt)
    my_logger.addHandler(file_handler)

    my_logger.info("Redfish Stress Test, version %s", TOOL_VERSION)
    my_logger.info("")

    if args.ip is None and configfile is None:
        my_logger.error('No IP or Config Specified')
        parser.print_help()
        return 1, None, 'Configuration Incomplete'

    # Handle config file
    #
    # if configfile:
    #     from common.config import convert_config_to_args
    #     convert_config_to_args(args, configfile)
    # else:
    #     from common.config import convert_args_to_config
    #     my_logger.info('Writing config file to log directory')
    #     configfilename = datetime.strftime(startTick, os.path.join(logpath, "ConfigFile_%m_%d_%Y_%H%M%S.ini"))
    #     my_config = convert_args_to_config(args)
    #     with open(configfilename, 'w') as f:
    #         my_config.write(f)

    scheme, netloc, _, _, _, _ = urlparse(args.ip)
    if scheme not in ['http', 'https']:
        my_logger.error('IP is missing http or https')
        return 1, None, 'IP Incomplete'

    if netloc == '':
        my_logger.error('IP is missing ip/host')
        return 1, None, 'IP Incomplete'

    # start printing config details, remove redundant/private info from print
    my_logger.info('Target URI: %s', args.ip)
    my_logger.info('\n'.join(
        ['{}: {}'.format(x, vars(args)[x] if x not in ['password'] else '******') for x in sorted(list(vars(args).keys() - set(['description']))) if vars(args)[x] not in ['', None]]))
    my_logger.info('Start time: %s', startTick.strftime('%x - %X'))
    my_logger.info("")

    firmware = getFirmwareVersion(args)
    my_logger.info('BMC Firmware Version: %s', firmware)
    my_logger.info("")

    # Start Main
    #status_code = 1
    #jsonData = None

    runtime = max(args.runtime, 1)

    my_logger.log(VERBOSE1, "Using a runtime of %d minutes", runtime)

    ###########################################################################
    # Execute requests stress test
    #
    # Sustained stress test
    #   --test_requests
    #   --requests_per_minute 30
    #   1 minute
    #       --runtime 1
    #   1 hour
    #       --runtime 60
    #   1 day
    #       --runtime 1440
    #
    # Max burst testing
    #   --requests_per_minute 500
    #   --runtime 1
    ###########################################################################
    if args.test_requests is True:
        my_logger.info("******************************************************")
        my_logger.info("Begin polling requests")

        if args.requests_per_minute > 0:
            rpm = args.requests_per_minute
        else:
            rpm = 30

        ret = doRequests(args, rpm, runtime)
        if ret != 0:
            my_logger.info('Request rate statistics failed')
            return 1

        my_logger.info('Request rate statistics')
        my_logger.info('\tRate achieved (requests/min): %d', final_rate)
        my_logger.info('\tMax call time (seconds): %.2f', max_call)
        my_logger.info('\tMin call time (seconds): %.2f', min_call)
        my_logger.info('\tAvg call time (seconds): %.2f', avg_call)
        my_logger.info('\tNumber of Redfish calls: %d', rate)
        my_logger.info('\tNumber of failures: %d', failures)

    ###########################################################################
    # Execute HSM style Redfish walk
    #
    # Standard options
    #   --runtime 1
    #   --test_rf_walk
    #   --walk_count 1
    ###########################################################################
    if args.test_rf_walk is True:
        my_logger.info("******************************************************")
        my_logger.info("Begin Redfish discovery tree walk")
        mincount = 1
        count = mincount

        if args.walk_count > mincount:
            count = args.walk_count

        my_logger.log(VERBOSE1, "Using a walk count of %d", count)

        ret = doRFWalk(args, count, runtime)
        if ret != 0:
            my_logger.info('Redfish walk rate statistics failed')
            return 1

        my_logger.info('Redfish discovery walk rate statistics')
        my_logger.info('\tRate achieved (requests/min): %d', final_rate)
        my_logger.info('\tMax call time (seconds) and url: %.2f (%s)', max_call, max_call_url)
        my_logger.info('\tMin call time (seconds) and url: %.2f (%s)', min_call, min_call_url)
        my_logger.info('\tAvg call time (seconds): %.2f', avg_call)
        my_logger.info('\tNumber of Redfish calls: %d', rate)
        my_logger.info('\tNumber of failures: %d', failures)

    return 0

if __name__ == '__main__':
    ret_code = main()
    sys.exit(ret_code)
