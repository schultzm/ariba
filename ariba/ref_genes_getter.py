class Error (Exception): pass

import sys
import os
import shutil
import re
import tarfile
import pyfastaq
import urllib.request
import time
import json
from ariba import common, card_record


class RefGenesGetter:
    def __init__(self, ref_db, genetic_code=11):
        allowed_ref_dbs = {'card', 'argannot', 'resfinder'}
        if ref_db not in allowed_ref_dbs:
            raise Error('Error in RefGenesGetter. ref_db must be one of: ' + str(allowed_ref_dbs) + ', but I got "' + ref_db)
        self.ref_db=ref_db
        self.genetic_code = genetic_code
        self.max_download_attempts = 3
        self.sleep_time = 2
        pyfastaq.sequences.genetic_code = self.genetic_code


    def _download_file(self, url, outfile):
        print('Downloading "', url, '" and saving as "', outfile, '" ...', end='', sep='')
        for i in range(self.max_download_attempts):
            time.sleep(self.sleep_time)
            try:
                urllib.request.urlretrieve(url, filename=outfile)
            except:
                continue
            break
        else:
            raise Error('Error downloading: ' + url)
        print(' done', flush=True)



    def _get_from_card(self, outprefix):
        outprefix = os.path.abspath(outprefix)
        tmpdir = outprefix + '.download'
        current_dir = os.getcwd()

        try:
            os.mkdir(tmpdir)
            os.chdir(tmpdir)
        except:
            raise Error('Error mkdir/chdir ' + tmpdir)

        card_version = '1.0.5'
        card_tarball_url = 'https://card.mcmaster.ca/download/0/broadsteet-v' + card_version + '.tar.gz'
        card_tarball = 'card.tar.gz'
        print('Working in temporary directory', tmpdir)
        print('Downloading data from card:', card_tarball_url, flush=True)
        common.syscall('wget -O ' + card_tarball + ' ' + card_tarball_url, verbose=True)
        print('...finished downloading', flush=True)
        if not tarfile.is_tarfile(card_tarball):
            raise Error('File ' + card_tarball + ' downloaded from ' + card_tarball_url + ' does not look like a valid tar archive. Cannot continue')

        json_file = './card.json'
        with tarfile.open(card_tarball, 'r') as tfile:
            tfile.extract(json_file)

        print('Extracted json data file ', json_file,'. Reading its contents...', sep='')

        variant_metadata_tsv = outprefix + '.metadata.tsv'
        presence_absence_fa = outprefix + '.presence_absence.fa'
        variants_only_fa = outprefix + '.variants_only.fa'
        f_out_tsv = pyfastaq.utils.open_file_write(variant_metadata_tsv)
        f_out_presabs = pyfastaq.utils.open_file_write(presence_absence_fa)
        f_out_var_only = pyfastaq.utils.open_file_write(variants_only_fa)

        with open(json_file) as f:
            json_data = json.load(f)

        json_data = {int(x): json_data[x] for x in json_data if not x.startswith('_')}
        print('Found', len(json_data), 'records in the json file. Analysing...', flush=True)

        for gene_key, gene_dict in sorted(json_data.items()):
            crecord = card_record.CardRecord(gene_dict)
            data = crecord.get_data()
            fasta_name_prefix = '.'.join([data[x] for x in ['ARO_id', 'ARO_accession']])

            for card_key, gi, genbank_id, strand, dna_seq in data['dna_seqs_and_ids']:
                fasta = pyfastaq.sequences.Fasta(fasta_name_prefix + '.' + gi + '.' + genbank_id + '.' + card_key, dna_seq)
                print(fasta.id, '.', '.', data['ARO_name'], sep='\t', file=f_out_tsv)
                if len(data['snps']) == 0:
                    print(fasta, file=f_out_presabs)
                    print(fasta.id, '.', '.', data['ARO_description'], sep='\t', file=f_out_tsv)
                else:
                    print(fasta, file=f_out_var_only)
                    for snp in data['snps']:
                        print(fasta.id, 'p', snp, data['ARO_description'], sep='\t', file=f_out_tsv)


        pyfastaq.utils.close(f_out_tsv)
        pyfastaq.utils.close(f_out_presabs)
        pyfastaq.utils.close(f_out_var_only)
        os.chdir(current_dir)
        print('Extracted data and written ARIBA input files\n')
        print('Final genes files and metadata file:')
        print('   ', presence_absence_fa)
        print('   ', variants_only_fa)
        print('   ', variant_metadata_tsv)

        print('\nYou can use those files with ARIBA like this:')
        print('ariba run --ref_prefix', outprefix, 'reads_1.fq reads_2.fq output_directory\n')

        print('If you use this downloaded data, please cite:')
        print('"The Comprehensive Antibiotic Resistance Database", McArthur et al 2013, PMID: 23650175')
        print('and in your methods say that version', card_version, 'of the database was used')


    def _get_from_resfinder(self, outprefix):
        outprefix = os.path.abspath(outprefix)
        final_fasta = outprefix + '.genes.fa'
        tmpdir = outprefix + '.tmp.download'
        current_dir = os.getcwd()

        try:
            os.mkdir(tmpdir)
            os.chdir(tmpdir)
        except:
            raise Error('Error mkdir/chdir ' + tmpdir)

        zipfile = 'resfinder.zip'
        cmd = 'curl -X POST --data "folder=resfinder&filename=resfinder.zip" -o ' + zipfile + ' https://cge.cbs.dtu.dk/cge/download_data.php'
        print('Downloading data with:', cmd, sep='\n')
        common.syscall(cmd)
        common.syscall('unzip ' + zipfile)

        print('Combining downloaded fasta files...')
        f = pyfastaq.utils.open_file_write(final_fasta)

        for filename in os.listdir('database'):
            if filename.endswith('.fsa'):
                print('   ', filename)
                file_reader = pyfastaq.sequences.file_reader(os.path.join('database', filename))
                for seq in file_reader:
                    print(seq, file=f)

        pyfastaq.utils.close(f)

        print('\nCombined files. Final genes file is callled', final_fasta, end='\n\n')
        os.chdir(current_dir)
        shutil.rmtree(tmpdir)

        print('You can use it with ARIBA like this:')
        print('ariba run --ref_prefix', outprefix, 'reads_1.fq reads_2.fq output_directory\n')
        print('If you use this downloaded data, please cite:')
        print('"Identification of acquired antimicrobial resistance genes", Zankari et al 2012, PMID: 22782487\n')


    def _get_from_argannot(self, outprefix):
        outprefix = os.path.abspath(outprefix)
        tmpdir = outprefix + '.tmp.download'
        current_dir = os.getcwd()

        try:
            os.mkdir(tmpdir)
            os.chdir(tmpdir)
        except:
            raise Error('Error mkdir/chdir ' + tmpdir)

        zipfile = 'arg-annot-database_doc.zip'
        self._download_file('http://www.mediterranee-infection.com/arkotheque/client/ihumed/_depot_arko/articles/304/arg-annot-database_doc.zip', zipfile)
        common.syscall('unzip ' + zipfile)
        os.chdir(current_dir)
        print('Extracted files.')

        genes_file = os.path.join(tmpdir, 'Database Nt Sequences File.txt')
        final_fasta = outprefix + '.fa'
        pyfastaq.tasks.to_fasta(genes_file, final_fasta)
        shutil.rmtree(tmpdir)

        print('Finished. Final genes file is called', final_fasta, end='\n\n')
        print('You can use it with ARIBA like this:')
        print('ariba run --ref_prefix', outprefix, 'reads_1.fq reads_2.fq output_directory\n')
        print('If you use this downloaded data, please cite:')
        print('"ARG-ANNOT, a new bioinformatic tool to discover antibiotic resistance genes in bacterial genomes",\nGupta et al 2014, PMID: 24145532\n')


    def run(self, outprefix):
        exec('self._get_from_' + self.ref_db + '(outprefix)')

