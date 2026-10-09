# Reviewed fixture specification; integration.py embeds the executable test_fixtures contract.
# Generate within the existing isolated root, then release it and prepare a NEW root binding.
{
 'schema': 1,
 'generator': ['build/elf/ldconfig', '-X', '-i', '-C',
               '/image-build/output/generated-ld.so.cache', '/usr/lib'],
 'artifact': 'generated-ld.so.cache',
 'destination': 'etc/ld.so.cache',
 'mode': 420,
 'requires_new_root_registration': True,
 'provenance': 'Use the freshly source-built ldconfig and libraries of the actual test root; never copy the host cache.',
 'validation': [
  ['bash', 'upstream/glibc-2.44/elf/tst-rtld-does-not-exist.sh', '/image-build/source/build/elf/ld.so'],
  ['bash', 'upstream/glibc-2.44/elf/tst-rtld-dash-dash.sh', '/image-build/source/build/elf/ld.so'],
 ],
}
