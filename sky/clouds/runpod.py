""" RunPod Cloud. """

import typing
from typing import Dict, Iterator, List, Optional, Tuple, Union

from sky import catalog
from sky import clouds
from sky.utils import registry
from sky.utils import resources_utils

if typing.TYPE_CHECKING:
    from sky import resources as resources_lib
    from sky.volumes import volume as volume_lib

_CREDENTIAL_FILES = [
    'config.toml',
]


@registry.CLOUD_REGISTRY.register
class RunPod(clouds.Cloud):
    """ RunPod GPU Cloud

    _REPR | The string representation for the RunPod GPU cloud object.
    """
    _REPR = 'RunPod'
    _CLOUD_UNSUPPORTED_FEATURES = {
        clouds.CloudImplementationFeatures.STOP: 'Stopping not supported.',
        clouds.CloudImplementationFeatures.MULTI_NODE:
            ('Multi-node not supported yet, as the interconnection among nodes '
             'are non-trivial on RunPod.'),
        clouds.CloudImplementationFeatures.CUSTOM_DISK_TIER:
            ('Customizing disk tier is not supported yet on RunPod.'),
        clouds.CloudImplementationFeatures.CUSTOM_NETWORK_TIER:
            ('Custom network tier is not supported yet on RunPod.'),
        clouds.CloudImplementationFeatures.STORAGE_MOUNTING:
            ('Mounting object stores is not supported on RunPod. To read data '
             'from object stores on RunPod, use `mode: COPY` to copy the data '
             'to local disk.'),
        clouds.CloudImplementationFeatures.HIGH_AVAILABILITY_CONTROLLERS:
            ('High availability controllers are not supported on RunPod.'),
        clouds.CloudImplementationFeatures.CUSTOM_MULTI_NETWORK:
            ('Customized multiple network interfaces are not supported on '
             'RunPod.'),
    }
    _MAX_CLUSTER_NAME_LEN_LIMIT = 120
    _regions: List[clouds.Region] = []

    PROVISIONER_VERSION = clouds.ProvisionerVersion.SKYPILOT
    STATUS_VERSION = clouds.StatusVersion.SKYPILOT
    OPEN_PORTS_VERSION = clouds.OpenPortsVersion.LAUNCH_ONLY

    @classmethod
    def _unsupported_features_for_resources(
        cls, resources: 'resources_lib.Resources'
    ) -> Dict[clouds.CloudImplementationFeatures, str]:
        """The features not supported based on the resources provided.

        This method is used by check_features_are_supported() to check if the
        cloud implementation supports all the requested features.

        Returns:
            A dict of {feature: reason} for the features not supported by the
            cloud implementation.
        """
        del resources  # unused
        return cls._CLOUD_UNSUPPORTED_FEATURES

    @classmethod
    def _max_cluster_name_length(cls) -> Optional[int]:
        return cls._MAX_CLUSTER_NAME_LEN_LIMIT

    @classmethod
    def regions_with_offering(cls, instance_type: str,
                              accelerators: Optional[Dict[str, int]],
                              use_spot: bool, region: Optional[str],
                              zone: Optional[str]) -> List[clouds.Region]:
        del accelerators  # unused
        regions = catalog.get_region_zones_for_instance_type(
            instance_type, use_spot, 'runpod')

        if region is not None:
            regions = [r for r in regions if r.name == region]

        if zone is not None:
            for r in regions:
                assert r.zones is not None, r
                r.set_zones([z for z in r.zones if z.name == zone])
            regions = [r for r in regions if r.zones]
        return regions

    @classmethod
    def get_vcpus_mem_from_instance_type(
        cls,
        instance_type: str,
    ) -> Tuple[Optional[float], Optional[float]]:
        return catalog.get_vcpus_mem_from_instance_type(instance_type,
                                                        clouds='runpod')

    @classmethod
    def zones_provision_loop(
        cls,
        *,
        region: str,
        num_nodes: int,
        instance_type: str,
        accelerators: Optional[Dict[str, int]] = None,
        use_spot: bool = False,
    ) -> Iterator[Optional[List['clouds.Zone']]]:
        del num_nodes  # unused
        regions = cls.regions_with_offering(instance_type,
                                            accelerators,
                                            use_spot,
                                            region=region,
                                            zone=None)
        for r in regions:
            assert r
            yield r.zones

    def instance_type_to_hourly_cost(self,
                                     instance_type: str,
                                     use_spot: bool,
                                     region: Optional[str] = None,
                                     zone: Optional[str] = None) -> float:
        return catalog.get_hourly_cost(instance_type,
                                       use_spot=use_spot,
                                       region=region,
                                       zone=zone,
                                       clouds='runpod')

    def accelerators_to_hourly_cost(self,
                                    accelerators: Dict[str, int],
                                    use_spot: bool,
                                    region: Optional[str] = None,
                                    zone: Optional[str] = None) -> float:
        """Returns the hourly cost of the accelerators, in dollars/hour."""
        del accelerators, use_spot, region, zone  # unused
        return 0.0  # RunPod includes accelerators in the hourly cost.

    def get_egress_cost(self, num_gigabytes: float) -> float:
        return 0.0

    @classmethod
    def get_default_instance_type(
            cls,
            cpus: Optional[str] = None,
            memory: Optional[str] = None,
            disk_tier: Optional[resources_utils.DiskTier] = None
    ) -> Optional[str]:
        """Returns the default instance type for RunPod."""
        return catalog.get_default_instance_type(cpus=cpus,
                                                 memory=memory,
                                                 disk_tier=disk_tier,
                                                 clouds='runpod')

    @classmethod
    def get_accelerators_from_instance_type(
            cls, instance_type: str) -> Optional[Dict[str, Union[int, float]]]:
        return catalog.get_accelerators_from_instance_type(instance_type,
                                                           clouds='runpod')

    @classmethod
    def get_zone_shell_cmd(cls) -> Optional[str]:
        return None

    def make_deploy_resources_variables(
        self,
        resources: 'resources_lib.Resources',
        cluster_name: resources_utils.ClusterName,
        region: 'clouds.Region',
        zones: Optional[List['clouds.Zone']],
        num_nodes: int,
        dryrun: bool = False,
        volume_mounts: Optional[List['volume_lib.VolumeMount']] = None,
    ) -> Dict[str, Optional[Union[str, bool]]]:
        del dryrun, cluster_name  # unused
        assert zones is not None, (region, zones)

        zone_names = [zone.name for zone in zones]

        resources = resources.assert_launchable()
        acc_dict = self.get_accelerators_from_instance_type(
            resources.instance_type)
        custom_resources = resources_utils.make_ray_custom_resources_str(
            acc_dict)

        if resources.image_id is None:
            image_id: Optional[str] = 'runpod/base:0.0.2'
        elif resources.extract_docker_image() is not None:
            image_id = resources.extract_docker_image()
        else:
            image_id = resources.image_id[resources.region]

        instance_type = resources.instance_type
        use_spot = resources.use_spot
        hourly_cost = self.instance_type_to_hourly_cost(
            instance_type=instance_type, use_spot=use_spot)

        # default to root
        docker_username_for_runpod = (resources.docker_username_for_runpod
                                      if resources.docker_username_for_runpod
                                      is not None else 'root')

        return {
            'instance_type': instance_type,
            'custom_resources': custom_resources,
            'region': region.name,
            'availability_zone': ','.join(zone_names),
            'image_id': image_id,
            'use_spot': use_spot,
            'bid_per_gpu': str(hourly_cost),
            'docker_username_for_runpod': docker_username_for_runpod,
        }

    def _get_feasible_launchable_resources(
        self, resources: 'resources_lib.Resources'
    ) -> 'resources_utils.FeasibleResources':
        """Returns a list of feasible resources for the given resources."""
        if resources.instance_type is not None:
            assert resources.is_launchable(), resources
            resources = resources.copy(accelerators=None)
            return resources_utils.FeasibleResources([resources], [], None)

        def _make(instance_list):
            resource_list = []
            for instance_type in instance_list:
                r = resources.copy(
                    cloud=RunPod(),
                    instance_type=instance_type,
                    accelerators=None,
                    cpus=None,
                )
                resource_list.append(r)
            return resource_list

        # Currently, handle a filter on accelerators only.
        accelerators = resources.accelerators
        if accelerators is None:
            # Return a default instance type
            default_instance_type = RunPod.get_default_instance_type(
                cpus=resources.cpus,
                memory=resources.memory,
                disk_tier=resources.disk_tier)
            if default_instance_type is None:
                # TODO: Add hints to all return values in this method to help
                #  users understand why the resources are not launchable.
                return resources_utils.FeasibleResources([], [], None)
            else:
                return resources_utils.FeasibleResources(
                    _make([default_instance_type]), [], None)

        assert len(accelerators) == 1, resources
        acc, acc_count = list(accelerators.items())[0]
        (instance_list,
         fuzzy_candidate_list) = catalog.get_instance_type_for_accelerator(
             acc,
             acc_count,
             use_spot=resources.use_spot,
             cpus=resources.cpus,
             region=resources.region,
             zone=resources.zone,
             clouds='runpod')
        if instance_list is None:
            return resources_utils.FeasibleResources([], fuzzy_candidate_list,
                                                     None)
        return resources_utils.FeasibleResources(_make(instance_list),
                                                 fuzzy_candidate_list, None)

    @classmethod
    def _check_compute_credentials(
            cls) -> Tuple[bool, Optional[Union[str, Dict[str, str]]]]:
        """Checks if the user has access credentials to
        RunPod's compute service."""
        return cls._check_credentials()

    @classmethod
    def _check_credentials(cls) -> Tuple[bool, Optional[str]]:
        """ Verify that the user has valid credentials for RunPod. """
        try:
            import runpod  # pylint: disable=import-outside-toplevel
            valid, error = runpod.check_credentials()

            if not valid:
                return False, (
                    f'{error} \n'  # First line is indented by 4 spaces
                    '    Credentials can be set up by running: \n'
                    f'        $ pip install runpod \n'
                    f'        $ runpod config\n'
                    '    For more information, see https://docs.skypilot.co/en/latest/getting-started/installation.html#runpod'  # pylint: disable=line-too-long
                )

            return True, None

        except ImportError:
            return False, ('Failed to import runpod. '
                           'To install, run: pip install skypilot[runpod]')

    def get_credential_file_mounts(self) -> Dict[str, str]:
        return {
            f'~/.runpod/{filename}': f'~/.runpod/{filename}'
            for filename in _CREDENTIAL_FILES
        }

    @classmethod
    def get_user_identities(cls) -> Optional[List[List[str]]]:
        # NOTE: used for very advanced SkyPilot functionality
        # Can implement later if desired
        return None

    def instance_type_exists(self, instance_type: str) -> bool:
        return catalog.instance_type_exists(instance_type, 'runpod')

    def validate_region_zone(self, region: Optional[str], zone: Optional[str]):
        return catalog.validate_region_zone(region, zone, clouds='runpod')

    @classmethod
    def get_image_size(cls, image_id: str, region: Optional[str]) -> float:
        # TODO: use 0.0 for now to allow all images. We should change this to
        # return the docker image size.
        return 0.0
