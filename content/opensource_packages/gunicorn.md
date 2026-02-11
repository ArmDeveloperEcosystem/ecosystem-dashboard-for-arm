---
name: Gunicorn
category: Web Server
description: Gunicorn 'Green Unicorn' is a Python WSGI HTTP Server for UNIX.
download_url: https://github.com/benoitc/gunicorn/releases?page=1
works_on_arm: true
supported_minimum_version:
    version_number: 17.5
    release_date: 2013/07/03


optional_info:
    homepage_url: http://www.gunicorn.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs:
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/django/deploy_django_application/
        partner_content:
    arm_recommended_minimum_version:
        version_number: 22.0.0
        release_date: 2024/04/17
        reference_content: https://github.com/benoitc/gunicorn/releases/tag/22.0.0
        rationale: This version introduces major HTTP parsing security improvements, fixing CVE-2024-1135 and blocking several request smuggling vectors. It refuses unsafe HTTP methods, headers, and transfer codings by default, breaking compatibility with some non-standard clients. The setup system migrates to pyproject.toml, worker liveness signaling uses utime, and support for Python 3.12 is added. Minimum supported Python version is now 3.7.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: It is platform independent, checked by building and running the first version released on GitHub. For arm_content, [this](https://learn.arm.com/learning-paths/servers-and-cloud-computing/django/deploy_django_application/) link has a section "Set up Gunicorn" which is required for deploying the Django application.

---
