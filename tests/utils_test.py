from collections import namedtuple
import os
import pytest

import pyfastaq

from viridian_workflow import utils

this_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(this_dir, "data", "utils")


def test_load_single_seq_fasta():
    expect = pyfastaq.sequences.Fasta("seq", "ACGT")
    infile = os.path.join(data_dir, "load_single_seq_fasta.ok.fa")
    assert expect == utils.load_single_seq_fasta(infile)
    infile = os.path.join(data_dir, "load_single_seq_fasta.bad1.fa")
    with pytest.raises(Exception):
        utils.load_single_seq_fasta(infile)
    infile = os.path.join(data_dir, "load_single_seq_fasta.bad2.fa")
    with pytest.raises(Exception):
        utils.load_single_seq_fasta(infile)

def test_load_amplicons_bed_file():
    Amplicon = namedtuple("Amplicon", ("name", "start", "end"))
    expect = [
        Amplicon("name1", 42, 99),
        Amplicon("name2", 85, 150),
    ]
    infile = os.path.join(data_dir, "load_amplicons_bed_file.bed")
    assert expect == utils.load_amplicons_bed_file(infile)

