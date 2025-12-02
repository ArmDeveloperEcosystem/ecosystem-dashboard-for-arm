---
name: GlusterFS
category: Storage
description: GlusterFS is an open-source, scalable distributed file system designed to handle large amounts of data across multiple servers.
download_url: https://github.com/gluster/glusterfs/tags
works_on_arm: true
supported_minimum_version:
    version_number: 9.0
    release_date: 2021/01/19

optional_info:
    homepage_url: https://www.gluster.org/
    support_caveats:
    alternative_options: 
    getting_started_resources:
        official_docs: https://docs.gluster.org/en/latest/Install-Guide/Install/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 11.0
        release_date: 2023/02/14
        reference_content: https://docs.gluster.org/en/main/release-notes/11.0/
        rationale: This release includes 36% performance boost for rmdir operations, expanded ZFS snapshot support, namespace-based quota implementation, and significant cleanups with improved readdir/readdirp efficiency. Many other major bugs have been resolved, for example, Geo-replication gsyncd at 100% CPU.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: There are no release notes or binaries present for Linux/ARM64. GlusterFS version 9.0 is installed and tested on the Neoverse N1, using steps mentioned in the [file](https://github.com/gluster/glusterfs/blob/devel/INSTALL).

---
