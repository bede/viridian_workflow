import sys

import mappy as mp
import pysam

from viridian_workflow.primers import AmpliconSet, get_tags, load_amplicon_schemes

from collections import namedtuple, defaultdict

BaseProfile = namedtuple(
    "BaseProfile", ["in_primer", "forward_strand", "amplicon_name"]
)


def mask_sequence(sequence, position_stats):
    sequence = list(sequence)
    qc = {}
    for position, stats in position_stats.items():
        if stats.check_for_failure():
            sequence[position] = "N"
            qc[position] = stats.log
    return "".join(sequence), qc


def test_bias(n, trials, threshold=0.3):
    """Test whether a number of boolean trials fit the binomial
    distribution
    """

    # TODO: decide whether to include scipy to use binom_test
    # or a pure python implementation.
    bias = abs(0.5 - (n / trials))
    return bias > threshold


class Stats:
    def __init__(self):
        self.alts_in_primer = 0
        self.refs_in_primer = 0

        self.alts_in_amplicons = defaultdict(int)
        self.refs_in_amplicons = defaultdict(int)
        self.amplicon_totals = defaultdict(int)

        self.alts_forward = 0
        self.refs_forward = 0

        self.alts = 0
        self.refs = 0
        self.total = 0
        self.log = []

    def add_alt(self, profile, alt=None):
        if profile.in_primer:
            self.alts_in_primer += 1
            return

        self.alts += 1

        if profile.amplicon_name:
            # when unambiguous amplicon call cannot be made, do not
            # consider (or consider differently)
            self.alts_in_amplicons[profile.amplicon_name] += 1
            self.amplicon_totals[profile.amplicon_name] += 1

        if profile.forward_strand:
            self.alts_forward += 1

        self.total += 1

    def add_ref(self, profile):
        if profile.in_primer:
            self.refs_in_primer += 1
            return

        self.alts += 1

        if profile.amplicon_name:
            self.refs_in_amplicons[profile.amplicon_name] += 1
            self.amplicon_totals[profile.amplicon_name] += 1

        if profile.forward_strand:
            self.refs_forward += 1

        self.total += 1

    def check_for_failure(self, minimum_depth=10, minimum_frs=0.7):
        """return whether a position should be masked
        """

        position_failed = False

        if self.total < minimum_depth:
            self.log.append(f"Insufficient depth to evaluate consensus")
            return True  # position failed

        # test total percentage of bases supporting consensus
        if self.refs / self.total < minimum_frs:
            self.log.append(f"Insufficient support of consensus base")
            position_failed = True
            if self.refs == 0:
                return position_failed

        # look for overrepresentation of alt alleles in regions covered
        # by primer sequences. This is reported but not as a failure
        if test_bias(self.refs_in_primer, self.refs):
            self.log.append("Consensus base calls are biased in primer region")

        # strand bias in alt calls
        if test_bias(self.refs_forward, self.refs):
            self.log.append("Strand bias for reads with reference alleles")
            position_failed = True

        # amplicon bias
        for amplicon, total in self.amplicon_totals.items():
            if test_bias(self.refs_in_amplicons[amplicon], total):
                self.log.append(
                    f"Amplicon bias in consensus allele calls, amplicon {amplicon}"
                )
                position_failed = True

        return position_failed

    def __str__(self):
        f = []
        if len(self.amps_total) > 1:
            return "-".join([f"{k}:{v}" for k, v in self.amps_total.items()])
        if self.alts / self.total > 0.2:
            return f"{self.alts}/{self.total}"
        return "-"


def cigar_to_alts(ref, query, cigar):
    """Interpret cigar string and query sequence in reference
    coords
    """
    positions = []
    q_pos = 0
    r_pos = 0
    for op, count in cigar:
        if op == 0:
            # match/mismatch
            for i in range(count):
                positions.append((r_pos + i, query[q_pos + i]))
            q_pos += count
            r_pos += count

        elif op == 1:
            pass
            # insertion
            #            positions.append((q_pos, query[q_pos : q_pos + count]))
            q_pos += count
            r_pos += 0

        elif op == 2:
            # deletion
            for n in range(count):
                positions.append((r_pos + n, "-"))
            r_pos += count

        elif op == 3:
            # ref_skip
            pass

        elif op == 4:
            # soft clip
            q_pos += count
            pass

        elif op == 5:
            # hard clip
            pass

        else:
            raise Exception(f"invalid cigar op {op}")

    return positions


def remap(reference_fasta, minimap_presets, amplicon_set, tagged_bam):
    stats = {}
    ref = mp.Aligner(reference_fasta, preset=minimap_presets)
    for r in pysam.AlignmentFile(tagged_bam):
        a = ref.map(r.seq)
        alignment = None
        for x in a:
            if x.is_primary:
                alignment = x

        if not alignment:
            continue

        tags = get_tags(r, amplicon_set.shortname)

        amplicon = None
        if len(tags) == 1:
            amplicon = amplicons[tags[0]]

        strand = False  # strand is forward
        if alignment.strand == 0:
            # should be error
            raise Exception()
        elif alignment.strand == 1:
            strand = True

        alts = cigar_to_alts(ref_seq[alignment.r_st : alignment.r_en], r.seq, r.cigar)

        for read_pos, base in alts:
            ref_position = read_pos + alignment.r_st

            # TODO resolve assumption: if there is an ambiguous amplicon id, in_primer is false
            in_primer = False
            if amplicon:
                in_primer = amplicon.position_in_primer(ref_position)

            base_profile = ReadProfile(in_primer, strand, amplicon.name)

            if ref_position not in stats:
                stats[ref_position] = Stats()
            if base != ref_seq[ref_position]:
                stats[ref_position].add_alt(base_profile)
            else:
                stats[ref_position].add_ref(base_profile)
    return stats


def mask(fasta, stats, name=None, prefix=None):
    seq = ""
    masked, log = mask_sequence(seq, stats)

    # write masked fasta
    with open(outpath, "w") as maskfd:
        print(">{name}\n{seq}", file=maskfd, end="")
    return outpath, log


if __name__ == "__main__":
    amplicon_sets = load_amplicon_sets(sys.argv[1])

    shortname = None
    ref_seq = None
    for s in mp.fastx_read(sys.argv[1]):
        ref_seq = s[1]

    amplicon_set = sys.argv[2]

    amplicons = {}
    for a, aset in amplicon_sets.items():
        if aset.name == sys.argv[2]:
            shortname = aset.shortname
            for amplicon in aset.tree:
                amplicon = amplicon.data
                amplicons[amplicon.shortname] = amplicon

    stats = remap(sys.argv[3], amplicon_set, sys.argv[4])

    for p in sorted(stats.keys()):
        if stats[p].total < 5:
            continue
        if str(stats[p]) == "-":
            continue
        print(p, stats[p])
