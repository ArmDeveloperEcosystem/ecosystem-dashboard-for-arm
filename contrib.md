# How to fill out metadata
The basic process to contribute a package is to:
1. Fork this repository.
2. Add new packages by copying and replacing an existing .md file. Contribute open-source packages in `/content/opensource_packages`, and commercial packages in `/content/commerial_packages`.
3. Open a Pull Request for review.

## Examples of packages to add
These are the types of packages you should look to contribute. In short, if it would help a developer migrate to Arm, it should be included.

| **Category**                             | **Examples**                                                                 |
|----------------------------------------  |------------------------------------------------------------------------------|
| **Languages (Interpreted and Compiled)** | Python, Java, Ruby, Perl, PHP, JavaScript / C++, C#, Go, Rust, Fortran, Swift |   
| **Critical Interpreted Language Modules**| Python's numpy, scipy, pandas, tensorflow, cython, multiprocessing. NodeJS's node-gyp, express, bcrpyt, grpc, bufferutil |   
| **Tools and Libraries**                  | x265, OpenSSL, Boost, TensorFlow, NumPy, libc, htop, perf, nmon, sysstat, dstat, gdb, valgrind, strace, CMake, Make, Bazel, apt, yum, pacman, iptables, firewalld | 
| **Frameworks and Middleware**            | Django, Spring, Ruby on Rails, Express, Laravel, Apache Hadoop, Apache Spark, PyTorch, Keras, scikit-learn, Istio, Consul, Jenkins, GitLab CI/CD, CircleCI, RabbitMQ, Apache Kafka, Kong, NGINX, Snort  | 
| **Databases**                            | MySQL, PostgreSQL, SQLite, MongoDB, Cassandra, Redis                         |  
| **Virtualization/Containerization**      | KVM, QEMU, Docker, Kubernetes, Docker Swarm, LXC/LXD                         | 
| **HPC Packages**                         | OpenMPI, MPICH, SLURM, Torque, HDF5, OpenBLAS, ATLAS, BLIS, LAPACK, PETSc, FFTW |


## Examples of what NOT TO ADD
These packages should NOT be added, as the trade-off between clutter and clarity is not high enough. 

| **Category**                             | **Examples**                                                                 |
|----------------------------------------  |------------------------------------------------------------------------------|
| **Small Interpreted Language Modules**   | Python's emoji, pyjokes, pytz. NodeJS's is-odd, node-fetch, chalk  |   
| **Multiple SDK installs of the same SW** | sentry-python, sentry-javascript, sentry-go | 

If it is not clear from existing package examples, view how to populate package metadata by expanding the section below.

<details>
  <summary>Metadata specific instructions</summary>

# Required Information
All of this data must be populated for this package to submit a valid package.

## name
Add the name of the package here.

`name: Ubuntu`

## category
Select the appropriate category for this package from the list of approved categories here. Select ONE category only, the closest match.

`category: Operating System`

## description
A one sentence description for this package; should be fairly high-level explaining what the package does or what value it provides.

`description: Ubuntu is a Linux distribution based on Debian for the enterprise server, desktop, cloud, and IoT. `

## download_url
The URL, starting with 'https://', that brings the reader to the place to download this package. Clicking this link should not go to the generic homepage, nor start auto-downloading the package itself. The download button should be easy to find on this page; use anchor tags on the page (with '#') if you cannot route a reader directly to the download area.
If you have to choose, default to linking to the most recent download for this package. If there is no binary to download and it must be built from source, link to the source location (which may be GitHub) as a last option.

`download_url: https://ubuntu.com/download/server/arm`

## works_on_arm
Either 'true' or 'false'. If 'false', please fill out the 'alternative_options' field below linking to another package that is supported by Arm that satisfies the same goals.

`works_on_arm: true`

## version
This field specifies both the supported_minimum and recommended_minimum versions for this package to run on Arm. You should also include the dates that each version was released; this gives helpful context to the reader to assist their analysis. If a version just says the month and year it was released, you can fill in the first of the month to use the ISO standard YYYY/MM/DD format. Here is a description of what both version fields mean:
supported_minimum   = The first version that enabled support for Arm hardware. This is an objective measurement, often found in package release notes or news.
recommended_minimum = The first version that enabled good/great performance on Arm hardware. This is a subjective measurement, and information can be found around release notes, news, and developer first-hand experience. 

`version:
- supported_minimum: 20.00.0
- supported_minimum_date: 2020/05/11
- recommended_minimum: 22.04.3
- recommended_minimum_date: 2022//04/21`

# Optional Data
These fields are an optional addition, adding more context to the package. Fill these out if appropriate.

## homepage_url
The URL, starting with 'https://', that brings the reader to the package homepage to learn more high-level info about it. Most packages should have this, with some smaller packages being the exception.

`- homepage_url: https://ubuntu.com/`

## support_caveats
This field allows context for the level of Arm support this package enjoys. For examples of what can go here, see below:
- If a package works on Arm but needs a specific library installed to work correctly, note that here.
- If a package works on some Arm servers but not others, note that here.
- If there is varying levels of support for this package across OSes, note that here.

`- support_caveats: `

## alternative_options
This field should be filled out if `works_on_arm: false`, but can be helpful context if set to true as well. List out alternative packages that address the same problem a developer is trying to solve. This will help route them to solve their problem on Arm even if the package they are looking up isn't currently supported.

`- alternative_options:  `

## getting_started_resources
This field is NOT for linking to a generic documentation site...developers can find that themselves. This is specifically for linking to content that gets a developer from 0 to a package installed and working. Do not link to generic documentation, nor to more complex ways to use this package on Arm. You can link to a documentation page that is specifically about getting the package installed & working on Arm if it exists.

## arm_content
This field is for ONE getting started link that lives on an Arm digital domain. Options, from most common first:
- Install Guides ->  [learn.arm.com/install-guides](https://learn.arm.com/install-guides)
- Learning Paths ->  https://learn.arm.com/learning-paths/servers-and-cloud-computing/codec/

`- arm_content:`

## partner_content
This field is for ONE getting started link that is made by Cloud Service Proviers. Common sources would be AWS, GCP, Azure, Ampere, etc.

`- partner_content:`

## official_docs
This field is for ONE getting started link that is from the official package documentation. Please link to the specific 'getting started' section in these docs, not just the generic docs link.

`- official_docs:`

</details>
