from __future__ import print_function

import time

import config
import erp_client
from ami_client import AMIClient
from call_manager import CallManager
from parser import parse_ami_message


def run():
    manager = CallManager()

    while True:
        client = AMIClient()

        try:
            print("Connecting to AMI {0}:{1}...".format(config.HOST, config.PORT))
            client.connect()
            print("Connected. Listening for clean call flow events...")

            for raw_message in client.read_messages():
                event = parse_ami_message(raw_message)

                for business_event in manager.process_event(event):
                    erp_client.handle_business_event(business_event)

        except KeyboardInterrupt:
            print("")
            print("Listener stopped by user.")
            client.close()
            break
        except Exception as exc:
            print("")
            print("Listener error: {0}".format(exc))
            client.close()
            print("Reconnecting in {0} seconds...".format(config.RECONNECT_DELAY))
            time.sleep(config.RECONNECT_DELAY)


if __name__ == "__main__":
    run()
