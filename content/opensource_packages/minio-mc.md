---
name: Minio-mc
category: Storage
description: Minio-mc is a command-line tool for managing MinIO and Amazon S3 compatible cloud storage services, enabling users to perform tasks like file uploads, downloads, and bucket management efficiently.
download_url: https://dl.min.io/client/mc/release/linux-arm64/
works_on_arm: true
supported_minimum_version:
    version_number: 2017-02-02T22:38:48Z
    release_date: 2017/02/03
 
 
optional_info:
    homepage_url: https://github.com/minio/mc
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://min.io/docs/minio/linux/reference/minio-mc.html
    arm_recommended_minimum_version:
        version_number: RELEASE.2024-04-18T16-45-29Z
        release_date: 2024/04/19
        reference_content: https://github.com/minio/mc/releases/tag/RELEASE.2024-04-18T16-45-29Z
        rationale: This version is a large bugfix release. This release introduces breaking changes to encryption-related flags for improved security and clarity. The old --encrypt, --encrypt-s3, and --encrypt-kms flags have been renamed to --enc-c, --enc-s3, and --enc-kms, respectively. These updated flags now only accept RawBase64-encoded keys and support multiple entries, while the older flags are no longer supported. Additionally, the --continue flag has been removed due to insecure behavior. Other notable changes include UI enhancements using the lipgloss table package for ILM commands, renaming of the mc idp ldap accesskey create --login command, removal of session code, updated dependencies, and minor UI cleanups.
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Release notes regarding Arm64/Linux support is not available but "2017-02-02T22:38:48Z" is the minimum version available for Arm64/Linux in it's archive repository for [prebuilt binary](https://dl.min.io/client/mc/release/linux-arm64/archive/). Tested the same by successfully installing it on Arm64/Linux platform.
 
---
