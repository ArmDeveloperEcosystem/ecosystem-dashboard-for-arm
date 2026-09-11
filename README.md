# Software Ecosystem Dashboard for Arm
The Software Ecosystem Dashboard for Arm is available at [https://developer.arm.com/ecosystem-dashboard/](https://developer.arm.com/ecosystem-dashboard/)

This repository is maintained by Arm and contains the source files for the Arm Software Ecosystem Dashboard, providing information on software packages that work on Arm. 
This data is sourced from Arm and third parties. While Arm uses reasonable efforts to keep this dashboard accurate, Arm does not warrant (express or implied) or provide any guarantee of data correctness due to the ever-evolving software landscape.  


# How To Contribute and Request:
* To contribute new package data (or improve existing package data):
    * Fork this repo and submit pull requests; follow the step by step instructions in [Contribution guidelines](/contrib.md).
* Log an issue with package data(or other general issues)
    * Log a [issue on GitHub](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/issues)
* Request for packages to be added to the dashboard
     * Submit the [request for package on GitHub](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/blob/main/.github/ISSUE_TEMPLATE/package-request.md)

Note that all site content, including new contributions, is licensed under a [Creative Commons Attribution 4.0 International license](https://creativecommons.org/licenses/by/4.0/).
Source repository for arm ecosystem dashboard that lists packages that work on Arm

# Directory Structure

This site is built on the [Hugo](https://gohugo.io/) web framework, ideal for generating static websites. Below is a brief description of the key files and directories:

  * /content
    * contains all package source data
  * /themes
    * where the html elements are defined to render /content into stylized HTML
  * LICENSE files
    * where the license information is contained

# Smoke Validation and Bounded Repair

The full Arm smoke cycle runs weekly, on manual dispatch on `main`, and after
smoke-code merges to `main`. Ordinary website-only changes do not launch the
smoke fleet. An authenticated failed batch may receive one fresh confirmation
retry at the same commit; original failures remain recorded.

An implemented, **disabled-by-default** repair path can then propose only
approved build-prerequisite additions, reduced build parallelism, or bounded
curl retry flags. It authenticates persistent failure evidence, requests one
data-only model proposal per package, enforces patch policy, stages an immutable
candidate branch, runs the actual package workflow on GitHub-hosted Arm, and
opens a draft PR only after verified native success. The limit is 10 packages
per incident and two parallel repairs; unsupported cases require manual work.

Not all packages or failure causes are automatically repairable. A layout-only
coverage scan of 960 registered packages admitted 554 layouts and rejected 406;
these are **not validated repair counts**. Callable-only or delegated layouts
require manual handling. No package workflows were changed to force eligibility.
See the [layout-admission coverage snapshot](.github/SMOKE_REPAIR.md#layout-admission-coverage).

Existing tests, assertions, outputs, and failure gates remain unchanged. A human
must review and merge any repair, and the new `main` must pass its own full
smoke cycle. This is not a universal fixer, does not manufacture green results,
and never automatically approves, merges, or deploys.

Repository/App/environment configuration and live repair integration are **not
completed or verified in this change**. Keep `SMOKE_REPAIR_ENABLED` unset or
`false`; the user tests first, Chris reviews next, and a human merges only after
the required checks and approvals. See [Smoke repair](.github/SMOKE_REPAIR.md)
for exact configuration, credential boundaries, and the rollout checklist.
