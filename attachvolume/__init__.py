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
    logging.getLogger('botocore').setLevel(logging.CRITICAL)
    logging.getLogger('urllib3').setLevel(logging.CRITICAL)
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
    try:
        response = requests.get(
            url,
            timeout=REQUESTS_TIMEOUT,
            headers={
                'Content-Type': 'json',
            }
        )
        return response.text

    # I really don't care why it fails
    except:  # pylint: disable=bare-except
        return ''


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
    parser.add_argument('--device',
                        dest='device',
                        required=False,
                        default='/dev/xvdf',
                        help="The device to attach the volume too")
    parser.add_argument('--instance_id', '--instance', '-i',
                        dest='instance',
                        required=False,
                        default=os.getenv('INSTANCE_ID', get_instanceid()),
                        help="The instance to attach too")
    parser.add_argument('--uuid', '-u',
                        dest='partition',
                        required=False,
                        default='',
                        help="The UUID of the partition to mount")
    parser.add_argument('--dst', '-d',
                        dest='mount_point',
                        required=False,
                        default='',
                        help="The where to mount the partition")
    parser.add_argument('--fstab',
                        dest='fstab',
                        required=False,
                        action='store_true',
                        default=False,
                        help="Write the mount context to fstab")
    parser.add_argument('--fs-type',
                        dest='fs_type',
                        required=False,
                        default='xfs',
                        help="What filesystem to mount")
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
    LOG.debug(json.dumps(response, default=str))
    if not len(response.get('Attachments', [])):  # pylint: disable=use-implicit-booleaness-not-len
        return 'detached'
    return response['Attachments'][0]['State']


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


def attach(volume_id: str, instance_id: str, device: str) -> None:
    """I execute the attach

    Args:
        volume_id (str): the volume to attach
        instance_id (str): the instance to attach the volume to
        device (sfr): the device to attach the volume too
    """
    response = EC2.attach_volume(
        Device=device,
        InstanceId=instance_id,
        VolumeId=volume_id
    )
    LOG.debug(json.dumps(response, default=str))
    volume_state_wait(volume_id, 'attached')
    LOG.info('%s is now attached', volume_id)


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
    LOG.info('%s is now detached', volume_id)


def is_attached_instance(volume: str, instance: str) -> bool:
    """_summary_

    Args:
        volume (str): _description_
        instance (str): _description_

    Returns:
        bool: _description_
    """
    response = EC2.describe_volumes(VolumeIds=[volume])['Volumes'][0]
    for attachment in response.get('Attachments', []):
        if attachment['InstanceId'] == instance:
            return True
    return False


def mount_partition(partition: str, mount_point: str) -> None:
    """Mount the partition to the mount point

    Args:
        partition (str): partition uuid to mount
        mount_point (str): where to mount the partition
    """
    command = f"/usr/bin/mount /dev/disk/by-uuid/{partition} {mount_point}\n"
    os.system(command)


def fstab(partition: str, mount_point: str, fstype: str) -> None:
    """Append to fstab

    Args:
        partition (str): partition uuid to mount
        mount_point (str): where to mount the partition
        fs_type (str): the filesystem type to use
    """
    with open('/etc/fstab', 'a', encoding='utf8') as handler:
        handler.write(
            f"UUID={partition}     {mount_point}     {fstype}     defaults,noatime 1 1\n"
        )


def main():
    """ Main body
    """
    args = _options()
    if is_attached(args.volume):
        if not args.force:
            LOG.info('%s is already attached to an instance', args.volume)
            sys.exit(1)

        if is_attached_instance(args.volume, args.instance):
            LOG.info('%s is already attached to %s', args.volume, args.instance)
            sys.exit(0)

        deattach(args.volume)

    # execute the attachement
    attach(args.volume, args.instance, args.device)

    # mount if we have all the context
    if args.partition and args.mount_point:
        mount_partition(args.partition, args.mount_point)

        if args.fstab:
            fstab(args.partition, args.mount_point, args.fs_type)


if __name__ == '__main__':
    main()
