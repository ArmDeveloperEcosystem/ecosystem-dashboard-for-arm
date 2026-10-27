require 'json'
require 'tmpdir'
require 'rbconfig'
require 'open3'

mode = ARGV.fetch(0, 'all')
raise 'Unknown source probe mode' unless %w[identity ohai resource native all].include?(mode)
raise 'License settings must not be supplied' unless %w[CHEF_LICENSE CHEF_LICENSE_KEY].all? { |key| ENV[key].to_s.empty? }

require 'chef'
require 'chef/resource/file'
require 'ohai'

expected_version = ENV.fetch('EXPECTED_CHEF_VERSION')
expected_revision = ENV.fetch('EXPECTED_CHEF_REVISION')
evidence_dir = ENV.fetch('EVIDENCE_DIR')
source_root = File.realpath(ENV.fetch('CHEF_SOURCE_ROOT'))
checks = []

def check!(checks, name)
  raise "FAILED: #{name}" unless yield

  checks << { name: name, status: 'passed' }
  puts "PASS: #{name}"
end

check!(checks, 'exact upstream source revision') do
  revision, status = Open3.capture2('git', '-C', source_root, 'rev-parse', 'HEAD')
  status.success? && revision.strip == expected_revision && File.realpath(Dir.pwd) == source_root
end
check!(checks, 'exact Chef source version') { Chef::VERSION == expected_version }
check!(checks, 'Chef libraries loaded from checked-out upstream source') do
  { 'chef' => '.', 'chef-config' => 'chef-config', 'chef-utils' => 'chef-utils' }.all? do |name, directory|
    spec = Gem.loaded_specs.fetch(name)
    spec.version.to_s == expected_version &&
      File.realpath(spec.full_gem_path) == File.realpath(File.join(source_root, directory))
  end
end

system = nil
if %w[ohai resource all].include?(mode)
  system = Ohai::System.new
  system.all_plugins(['os', 'platform'])
  check!(checks, 'Ohai detects Ubuntu 24.04') do
    system['os'] == 'linux' && system['platform'] == 'ubuntu' && system['platform_version'] == '24.04'
  end
end

if %w[resource all].include?(mode)
  # Exercise the upstream resource API against real files, without RSpec or mocks.
  Dir.mktmpdir('chef-source-proof-') do |directory|
    path = File.join(directory, 'managed.txt')
    Chef::Config[:file_backup_path] = File.join(directory, 'backups')
    Chef::Config[:file_cache_path] = File.join(directory, 'cache')
    node = Chef::Node.new
    %w[os platform platform_family platform_version].each { |key| node.automatic[key] = system[key] }
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
end

native_objects = []
if %w[native all].include?(mode)
  check!(checks, 'native Linux Arm64 Ruby and host') do
    host, status = Open3.capture2('uname', '-m')
    status.success? && host.strip == 'aarch64' && RUBY_PLATFORM.include?('linux') &&
      RbConfig::CONFIG.fetch('host_cpu') == 'aarch64'
  end
  native_objects = Dir.glob(File.join(ENV.fetch('BUNDLE_PATH'), '**', '*.so'))
    .select { |path| File.file?(path) && !File.symlink?(path) }.sort.map do |path|
    description, status = Open3.capture2('file', '-b', path)
    raise "Not an ARM64 native dependency: #{path}" unless status.success? && description.include?('ELF 64-bit') && description.include?('ARM aarch64')

    { path: path, description: description.strip }
  end
  check!(checks, 'native dependency objects exist and are ARM64') { !native_objects.empty? }
end

result = {
  scope: 'upstream Chef source file-resource API, not vendor installer or CLI',
  mode: mode, version: Chef::VERSION, source_revision: expected_revision,
  ruby: RUBY_DESCRIPTION, platform: RUBY_PLATFORM, source_root: source_root,
  checks: checks, native_objects: native_objects
}
File.write(File.join(evidence_dir, "#{mode}.json"), JSON.pretty_generate(result) + "\n")
File.write(File.join(evidence_dir, 'source-version.txt'), Chef::VERSION + "\n")
if mode == 'identity'
  File.open(ENV.fetch('GITHUB_OUTPUT'), 'a') { |file| file.puts "version=#{Chef::VERSION}" }
end
puts JSON.pretty_generate(result)
