# Redfish Stress test

## About
Knowing the limitations of a particular Redfish implementation on a BMC enables
clients to provide improved management of the BMC. This stress test helps
determine sustained, burst, an concurrent access to the BMC and its Redfish
implementation.

## Pre-requisites
* python3
* pip3

## Installation
1. Create and activate python3 virtual environment.
   ```
   # python3 -m venv stress
   # cd stress
   # . bin/activate
   ```
1. Clone stress test repo
   ```
   # git clone git@github.com:Cray-HPE/redfish-stress-test.git
   ```
   or
   ```
   # git clone https://github.com/Cray-HPE/redfish-stress-test.git
   ```
1. Install local requirements.
   ```
   # cd redfish-stress-test
   # pip3 install -r requirements.txt
   ```
## Execute the Redfish Stress Test
1. Set **PASSWD** and **ENDPOINT** variables.
   ```
   # read -s PASSWD
   <enter redfish root password>
   # ENDPOINT=<hostname or IP>
   ```
1. Test sustained communication
   Make calls to the Redfish endpoint at a rate of 1 call every 60/requests_per_minute seconds.
   ```
   # python3 RedfishStressTest.py -i https://$ENDPOINT -u root -p $PASSWD --test_requests --requests_per_minute 30 --runtime 5
   ```
1. Test peak load
   Make calls to the Redfish endpoint as quickly as possible.
   ```
   python3 RedfishStressTest.py -i https://$ENDPOINT -u root -p $PASSWD --test_requests --requests_per_minute 500 --runtime 1
   ```
1. Test Redfish tree walk
   ```
   python3 RedfishStressTest.py -i https://$ENDPOINT -u root -p $PASSWD --test_rf_walk --runtime 1 --walk_count 10
   ```
A summary is displayed at the end of the execution. A **.txt** file is created in the **logs** directory for further analysis.

