"""
    I attach a volume to the instance.
"""


import argparse
import json
import logging
import os
import sys
import time


import boto3
import requests


LOG = logging.getLogger(__name__)
LOG_LEVEL = logging.INFO
if os.getenv('DEBUG', None):
    LOG_LEVEL = logging.DEBUG
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(message)s",
    stream=sys.stdout
)


EC2 = boto3.client('ec2')
REQUESTS_TIMEOUT = 1


def get_instanceid() -> str:
    """I return the instance_id for the current instance

    Returns:
        str: _description_
    """
    url = 'http://169.254.169.254/latest/meta-data/instance-id'
    response = requests.get(
        url,
        timeout=REQUESTS_TIMEOUT,
        headers={
            'Content-Type': 'json',
        }
    )
    LOG.debug('get recipe return code is %s', response.status_code)
    LOG.debug('get recipe text is %s', response.text)
    return json.loads(response.text)


def _options() -> object:
    """
        I provide the argparse option set.

        Returns
            argparse parser object.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--volume-id',  '--volume', '-v',
                        dest='volume',
                        required=True,
                        default='',
                        help='The volume id to attach')
    parser.add_argument('--detach', '--force', '-f',
                        dest='force',
                        required=False,
                        action='store_true',
                        default=False,
                        help="Detach the volume if its attached to another instance")
    parser.add_argument('--instance_id', '--instance', '-i',
                        dest='instance',
                        required=False,
                        default=os.getenv('INSTANCE_ID', get_instanceid()),
                        help="The instance to attach too")
    return parser.parse_args()


def get_volume_state(volume: str) -> str:
    """I return the state of a volume

    Args:
        volume (str): the volume_id to get the state

    Returns:
        str: the state of the volume_id
            one of ['attaching', 'attached', 'detaching', 'detached', 'busy']
    """
    LOG.debug('VolumeId is %s', volume)
    response = EC2.describe_volumes(VolumeIds=[volume])['Volumes'][0]
    if response.get('Attachments', False):
        return 'detached'
    return response['Attachments']['State']


def is_attached(volume_id: str) -> bool:
    """I check the volume to see if its attached

    Args:
        volume_id (str): the volume_id to check to be attached

    Returns:
        bool: True if it is attached, False if not.
    """
    state = get_volume_state(volume_id)
    if state == 'attached':
        return True
    return False


def volume_state_wait(volume: str, desired_state: str) -> None:
    """Wait for the volume to change state

    Args:
        volume (str): The volume to watch
        desired_state (str): The state we are looking for
    """
    while True:
        time.sleep(3)
        state = get_volume_state(volume)
        if state == desired_state:
            break


def attach(volume_id: str, instance_id: str) -> None:
    """I execute the attach

    Args:
        volume_id (str): the volume to attach
        instance_id (str): the instance to attach the volume to
    """
    response = EC2.attach_volume(
        Device='/dev/xvdf',
        InstanceId=instance_id,
        VolumeId=volume_id
    )
    LOG.debug(json.dumps(response, default=str))
    volume_state_wait(volume_id, 'attached')
    LOG.info('%s is now attached')


def deattach(volume_id: str) -> None:
    """I execute the deattach

    Args:
        volume_id (str): the volume to attach
        instance_id (str): the instance to attach the volume to
    """
    response = EC2.detach_volume(
        Force=True,
        VolumeId=volume_id
    )
    LOG.debug(json.dumps(response, default=str))
    volume_state_wait(volume_id, 'detached')
    LOG.info('%s is now detached')


def is_attached_instance(volume: str, instance: str) -> bool:
    """_summary_

    Args:
        volume (str): _description_
        instance (str): _description_

    Returns:
        bool: _description_
    """
    response = EC2.describe_volumes(VolumeIds=[volume])['Volumes']
    for attachment in response.get('Attachments', []):
        if attachment['InstanceId'] == instance:
            return True
    return False


def main():
    """ Main body
    """
    args = _options()
    if is_attached(args.volume):
        if not args.force:
            LOG.info('%s is already attached to an instance')
            sys.exit(1)

        if is_attached_instance(args.volume, args.instance):
            LOG.info('%s is already attached to requested instance')
            sys.exit(0)

        deattach(args.volume)

    # execute the attachement
    attach(args.volume, args.instance)


if __name__ == '__main__':
    main()
