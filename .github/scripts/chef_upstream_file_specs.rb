require 'json'
require 'rspec/core'

evidence_dir = ENV.fetch('EVIDENCE_DIR')
report_path = File.join(evidence_dir, 'upstream-rspec.json')
status = RSpec::Core::Runner.run([
  'spec/functional/resource/file_spec.rb',
  '--format', 'progress', '--format', 'json', '--out', report_path
])

# Preserve upstream filtering, but disclose every example it did not select.
examples = RSpec.world.example_groups.flat_map(&:descendants).flat_map(&:examples).uniq
selected = RSpec.world.filtered_examples.values.flatten.uniq
excluded = examples - selected
summary = JSON.parse(File.read(report_path)).fetch('summary')
raise 'Selected examples differ from executed report' unless selected.length == summary.fetch('example_count')
raise 'No upstream examples executed' if selected.empty?

inventory = {
  scope: 'one upstream functional file-resource spec with unchanged upstream filters',
  discovered_examples: examples.length,
  executed_examples: selected.length,
  excluded_examples: excluded.length,
  failed_examples: summary.fetch('failure_count'),
  pending_examples: summary.fetch('pending_count'),
  exclusions: excluded.map do |example|
    {
      id: example.id,
      description: example.full_description,
      file: example.metadata[:file_path],
      line: example.metadata[:line_number],
      boolean_tags: example.metadata.select { |_key, value| value == true || value == false }
    }
  end
}
File.write(File.join(evidence_dir, 'upstream-selection.json'), JSON.pretty_generate(inventory) + "\n")
puts JSON.pretty_generate(inventory.reject { |key, _value| key == :exclusions })
exit(status)
