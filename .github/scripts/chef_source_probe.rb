require 'json'
require 'tmpdir'
require 'rbconfig'
require 'chef'
require 'chef/resource/file'
require 'ohai'

expected_version = ENV.fetch('EXPECTED_CHEF_VERSION')
expected_revision = ENV.fetch('EXPECTED_CHEF_REVISION')
evidence_dir = ENV.fetch('EVIDENCE_DIR')
source_root = File.realpath(Dir.pwd)
checks = []
system = Ohai::System.new
system.all_plugins(['os', 'platform'])

def check!(checks, name)
  raise "FAILED: #{name}" unless yield

  checks << { name: name, status: 'passed' }
  puts "PASS: #{name}"
end

check!(checks, 'native Linux Arm64 Ruby') do
  RUBY_PLATFORM.include?('linux') && RbConfig::CONFIG.fetch('host_cpu') == 'aarch64'
end
check!(checks, 'Ohai detects Ubuntu 24.04') do
  system['os'] == 'linux' && system['platform'] == 'ubuntu' && system['platform_version'] == '24.04'
end
check!(checks, 'exact Chef source version') { Chef::VERSION == expected_version }
check!(checks, 'Chef loaded from checked-out upstream source') do
  File.realpath(Gem.loaded_specs.fetch('chef').full_gem_path) == source_root
end
check!(checks, 'no license-acceptance setting supplied by harness') do
  %w[CHEF_LICENSE CHEF_LICENSE_KEY].all? { |key| ENV[key].to_s.empty? }
end

# Exercise the public resource API against real temporary files, without mocks.
Dir.mktmpdir('chef-source-proof-') do |directory|
  path = File.join(directory, 'managed.txt')
  Chef::Config[:file_backup_path] = File.join(directory, 'backups')
  Chef::Config[:file_cache_path] = File.join(directory, 'cache')
  node = Chef::Node.new
  %w[os platform platform_family platform_version].each do |key|
    node.automatic[key] = system[key]
  end
  context = Chef::RunContext.new(node, {}, Chef::EventDispatch::Dispatcher.new)

  make_resource = lambda do |content|
    resource = Chef::Resource::File.new(path, context)
    resource.content(content)
    resource.mode('0600')
    resource.backup(false)
    resource
  end

  initial = make_resource.call("Chef #{expected_version} source on Arm64\n")
  initial.run_action(:create)
  check!(checks, 'resource creates exact file content') do
    File.binread(path) == "Chef #{expected_version} source on Arm64\n" && initial.updated_by_last_action?
  end
  check!(checks, 'resource applies requested file mode') { (File.stat(path).mode & 0o777) == 0o600 }

  original_stat = File.stat(path)
  identical = make_resource.call("Chef #{expected_version} source on Arm64\n")
  identical.run_action(:create)
  check!(checks, 'unchanged resource is idempotent') do
    !identical.updated_by_last_action? && File.stat(path).mtime == original_stat.mtime &&
      File.stat(path).ino == original_stat.ino
  end

  replacement = make_resource.call("Updated by Chef #{expected_version}\n")
  replacement.run_action(:create)
  check!(checks, 'resource updates file content') do
    File.binread(path) == "Updated by Chef #{expected_version}\n" && replacement.updated_by_last_action?
  end

  deletion = Chef::Resource::File.new(path, context)
  deletion.run_action(:delete)
  check!(checks, 'resource deletes file') { !File.exist?(path) && deletion.updated_by_last_action? }
end

result = {
  scope: 'upstream Chef source file-resource API, not vendor installer or CLI',
  version: Chef::VERSION,
  source_revision: expected_revision,
  ruby: RUBY_DESCRIPTION,
  platform: RUBY_PLATFORM,
  source_root: source_root,
  checks: checks
}
File.write(File.join(evidence_dir, 'resource-probe.json'), JSON.pretty_generate(result) + "\n")
puts JSON.pretty_generate(result)
