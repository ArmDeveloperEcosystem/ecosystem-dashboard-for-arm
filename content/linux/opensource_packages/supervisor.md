---
name: Supervisor
category: Miscellaneous
description: Supervisor is a client-server system which helps its users monitor and control processes on UNIX-like operating systems.
download_url: https://pypi.org/project/supervisor/#history
works_on_arm: true
supported_minimum_version:
    version_number: 3.0
    release_date: 2013/07/31


optional_info:
    homepage_url: http://supervisord.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: http://supervisord.org/installing.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 4.2.5
        release_date: 2022/12/24
        reference_content: https://supervisord.org/changes.html#id1
        rationale: This release fixes key bugs, including proper XML-RPC error handling and a UnicodeDecodeError in the web UI on Python 2.7. Deprecated Python APIs (e.g., asyncore, asynchat, and urllib.parse functions) were removed for compatibility with Python 3.8+ and 3.10+. Logging for unexpected subprocess exit codes is now at the WARN level. Performance was improved with faster file descriptor cleanup using os.closerange(). Minor usability enhancements were made to supervisorctl shutdown and XML-RPC response details.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no Linux/ARM64 release notes. Supervisor can be installed via pip. The minimum stable release on pypi after 2011 is version 3.0. All pypi releases have none-any wheels for supervisor.

---
