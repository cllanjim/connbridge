import os
import bridge_generator

bridge_generator.gen_protocol_if_needed()
execfile(bridge_generator.file_to_gen)
