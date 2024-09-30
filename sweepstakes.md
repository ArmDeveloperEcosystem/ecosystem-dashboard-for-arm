## Arm Cloud Software Scavenger Hunt
Welcome to the October 2024 sweepstakes involving Arm cloud developers from around the globe! 
**Your mission:** Locate packages that work on Arm Linux servers (Aarch64) and bring them back to one central place: [The Software Ecosystem Dashboard for Arm](https://www.arm.com/developer-hub/ecosystem-dashboard/).
**Your reward:** Submitting at least one original contribution enters you into a sweepstakes to receive Arm SWAG and recognition of your findings!
View the full [Terms and Conditions here.](https://www.arm.com/-/media/files/pdf/terms-and-conditions/arm-cloud-software-scavenger-hunt-terms-and-conditions)

### How do I get involved?
Simply contribute a package to the Software Ecosystem Dashboard for Arm through this GitHub repository! Simply follow this process below:

1. **Ensure the package does not already exist on the dashboard and verify it works on Arm Linux Servers.**  
   You’ll need to prove that it works on Arm in one of the following ways:
   1. Cite release notes that confirm Arm Linux server (aarch64) support.
   2. Provide a link where Aarch64 binaries are available for download.
   3. Manually validate that the package runs on Arm by following these steps:
     - Spin up an Arm Neoverse-based server (such as an AWS Graviton instance) running Linux (Ubuntu, RHEL, or SUSE preferred).
     - Install the package via a package manager or binary (build from source as a last resort).
     - Execute the package (e.g., run `package --version`) to confirm it works.
     - Document the process in the `optional_hidden_info` metadata field in your contribution.

2. **Fork this repository.**

3. **Add the package metadata.**  
   - Record relevant metadata, including how it works on Arm, in an `.md` file.
   - The easiest way is to copy an existing `.md` file and replace the content with the information for the new package.
   - For detailed instructions on metadata, refer to the [contribution guidelines](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/blob/main/contrib.md#required-information).

4. **Make a Pull Request.**  
   - Don’t forget to check the box to join the sweepstakes!

   
Arm engineers will review your submission, ask questions if needed, and then accept your contribution! In a week or so it will appear on the public dashboard.

### When will I know if I won the sweepstakes results?
About 1-2 weeks after the sweepstakes ends at the end of the month. Your GitHub username will be mentioned in this repository; respond to us within 14 days of being mentioned and we'll send you your SWAG ) and recognition.
