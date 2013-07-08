import sys
from abstract_step import *
import pipeline
import re
import process_pool
import yaml

class Cutadapt(AbstractStep):
    '''
    The cutadapt step can be used to clip adapter sequences from RNASeq reads.
    
    Any adapter may contain ``((INDEX))`` which will be replaced with every
    sample's index. The resulting adapter is checked for sanity and an
    exception is thrown if the adapter looks non-legit.
    '''
    
    def __init__(self, pipeline):
        super(Cutadapt, self).__init__(pipeline)
        
        self.set_cores(3)
        
        self.add_connection('in/reads')
        self.add_connection('out/reads')
        self.add_connection('out/log')
        
        self.require_tool('cat4m')
        self.require_tool('pigz')
        self.require_tool('cutadapt')
        self.require_tool('fix_qnames')
        
        self.add_option('adapter-R1', str)
        self.add_option('adapter-R2', str)
        self.add_option('fix_qnames', bool, default = False)
        
        '''
        self.add_option('adapter', str, list) # list for paired-end reads, string for single-end reads
        '''

    def setup_runs(self, complete_input_run_info, connection_info):
        output_run_info = {}
        for step_name, step_input_info in complete_input_run_info.items():
            for input_run_id, input_run_info in step_input_info.items():
                for in_path in sorted(input_run_info['output_files']['reads'].keys()):
                    suffix = ''
                    which = None
                    if self.find_upstream_info(input_run_id, 'paired_end'):
                        #which = input_run_info['info']['read_number'][os.path.basename(in_path)]
                        which = ''
                        if '_R1' in os.path.basename(in_path):
                            which = 'R1'
                        elif '_R2' in os.path.basename(in_path):
                            which = 'R2'
                        if not which in ['R1', 'R2']:
                            raise StandardError("Expected R1 and R2 input files, but got this: " + in_path)
                        suffix = '-' + which

                    output_run_id = input_run_id + suffix

                    if not output_run_id in output_run_info:
                        output_run_info[output_run_id] = {
                            'output_files': {},
                            'info': {}
                        }
                        if self.find_upstream_info(input_run_id, 'paired_end'):
                            output_run_info[output_run_id]['info']['read_number'] = which

                    # find adapter
                    adapter = self.option('adapter' + suffix)

                    # insert correct index if necessary
                    if '((INDEX))' in adapter:
                        index = self.find_upstream_info(input_run_id, 'index')
                        adapter = adapter.replace('((INDEX))', index)

                    # make sure the adapter is looking good
                    if re.search('^[ACGT]+$', adapter) == None:
                        raise StandardError("Unable to come up with a legit-looking adapter: " + adapter)
                    output_run_info[output_run_id]['info']['adapter'] = adapter

                    for t in [('reads', input_run_id + '-cutadapt' + suffix + '.fastq.gz'),
                            ('log', input_run_id + '-cutadapt' + suffix + '-log.txt')]:
                        pathkey = t[0]
                        path = t[1]
                        if not pathkey in output_run_info[output_run_id]['output_files']:
                            output_run_info[output_run_id]['output_files'][pathkey] = {}
                        if not path in output_run_info[output_run_id]['output_files'][pathkey]:
                            output_run_info[output_run_id]['output_files'][pathkey][path] = []
                        output_run_info[output_run_id]['output_files'][pathkey][path].append(in_path)

        return output_run_info

    def execute(self, run_id, run_info):
        # basic sanity check
        if len(run_info['output_files']['reads']) != 1:
            raise StandardError("Expected a single output file.")

        with process_pool.ProcessPool(self) as pool:
            with pool.Pipeline(pool) as pipeline:
                # set up processes
                cat4m = [self.tool('cat4m')]
                cat4m.extend(*sorted(run_info['output_files']['reads'].values()))

                pigz1 = [self.tool('pigz'), '--processes', '1', '--decompress', '--stdout']
                
                fix_qnames = [self.tool('fix_qnames')]

                cutadapt = [self.tool('cutadapt'), '-a', run_info['info']['adapter'], '-']

                pigz2 = [self.tool('pigz'), '--blocksize', '4096', '--processes', '1', '--stdout']

                # create the pipeline and run it
                pipeline.append(cat4m)
                pipeline.append(pigz1)
                if self.option('fix_qnames') == True:
                    pipeline.append(fix_qnames)
                pipeline.append(cutadapt, stderr_path = run_info['output_files']['log'].keys()[0])
                pipeline.append(pigz2, stdout_path = run_info['output_files']['reads'].keys()[0])
