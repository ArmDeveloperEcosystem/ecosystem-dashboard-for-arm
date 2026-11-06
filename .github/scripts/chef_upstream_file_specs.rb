require 'json'
require 'rspec/core'

raise 'License settings must not be supplied' unless %w[CHEF_LICENSE CHEF_LICENSE_KEY].all? { |key| ENV[key].to_s.empty? }
evidence_dir = ENV.fetch('EVIDENCE_DIR')
report_path = File.join(evidence_dir, 'upstream-rspec.json')
status = RSpec::Core::Runner.run([
  'spec/functional/resource/file_spec.rb',
  '--format', 'progress', '--format', 'json', '--out', report_path
])

# Inventory existing upstream filters; never alter them to increase passing counts.
examples = RSpec.world.example_groups.flat_map(&:descendants).flat_map(&:examples).uniq
selected = RSpec.world.filtered_examples.values.flatten.uniq
excluded = examples - selected
report = JSON.parse(File.read(report_path))
summary = report.fetch('summary')
reported = report.fetch('examples')
selected_ids = selected.map(&:id)
reported_ids = reported.map { |example| example.fetch('id') }
raise 'Duplicate discovered example IDs' unless examples.map(&:id).uniq.length == examples.length
raise 'Duplicate executed example IDs' unless reported_ids.uniq.length == reported_ids.length
raise 'Selected examples differ from executed report' unless selected_ids.sort == reported_ids.sort &&
  selected.length == summary.fetch('example_count')
raise 'No upstream examples executed' if selected.empty?

inventory = {
  scope: 'one upstream functional file-resource spec with unchanged upstream filters',
  version: ENV.fetch('EXPECTED_CHEF_VERSION'), source_revision: ENV.fetch('EXPECTED_CHEF_REVISION'),
  discovered_examples: examples.length, executed_examples: selected.length,
  excluded_examples: excluded.length, failed_examples: summary.fetch('failure_count'),
  pending_examples: summary.fetch('pending_count'),
  outside_example_errors: summary.fetch('errors_outside_of_examples_count'),
  exclusions: excluded.map do |example|
    {
      id: example.id, description: example.full_description,
      file: example.metadata[:file_path], line: example.metadata[:line_number],
      boolean_tags: example.metadata.select { |_key, value| value == true || value == false }
    }
  end
}
File.write(File.join(evidence_dir, 'upstream-selection.json'), JSON.pretty_generate(inventory) + "\n")
puts JSON.pretty_generate(inventory)
counts = "#{examples.length} registered, #{selected.length} executed, #{excluded.length} filtered, " \
  "#{summary.fetch('failure_count')} failed, #{summary.fetch('pending_count')} pending, " \
  "#{summary.fetch('errors_outside_of_examples_count')} outside-example errors"
File.write(File.join(evidence_dir, 'spec-summary.txt'), counts + "\n")
if ENV['GITHUB_STEP_SUMMARY']
  File.open(ENV.fetch('GITHUB_STEP_SUMMARY'), 'a') do |file|
    file.puts "Chef source #{ENV.fetch('EXPECTED_CHEF_VERSION')}: #{counts}. Filtered examples were not executed."
  end
end
exit(status) unless status == 0
raise 'Upstream examples failed or did not execute successfully' unless reported.all? { |example| example.fetch('status') == 'passed' }
raise 'Invalid upstream summary' unless %w[failure_count pending_count errors_outside_of_examples_count].all? { |key| summary.fetch(key) == 0 }
