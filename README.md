# ecosystem-dashboard-for-arm
The Software Ecosystem Dashboard for Arm is available at https://www.arm.com/developer-hub/ecosystem-dashboard/servers-and-cloud-computing/

This repository is maintained by Arm and contains the source files for the Arm Software Ecosystem Dashboard, providing information on software packages that work on Arm. 
This data is sourced from Arm and third parties. While Arm uses reasonable efforts to keep this dashboard accurate, Arm does not warrant (express or implied) or provide any guarantee of data correctness due to the ever-evolving software landscape.  

# How To Contribute:

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
  * config.toml
    * where the high-level website configuration settings are defined

