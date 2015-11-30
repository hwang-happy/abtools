#!/usr/bin/env python
# filename: scpcr_demultiplexing.py


#
# Copyright (c) 2015 Bryan Briney
# License: The MIT license (http://opensource.org/licenses/MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software
# and associated documentation files (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge, publish, distribute,
# sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
# BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#


from __future__ import print_function

import logging
import os
import sqlite3
import subprocess as sp
import sys
import tempfile
import time

from Bio import SeqIO

from abtools.utils.sequence import Sequence


logger = logging.getLogger('cluster')


class Cluster(object):
	"""docstring for Cluster"""
	def __init__(self, arg):
		super(Cluster, self).__init__()
		self.arg = arg



def cdhit(seqs, out_file=None, temp_dir=None, threshold=0.975, make_db=False):
	'''
	Perform CD-HIT clustering on a set of sequences.

	Inputs are an iterable of sequences, which can be any of the following:
		1) a sequence, as a string
		2) an iterable, formatted as (seq_id, sequence)
		3) a Biopython SeqRecord object
		4) an AbTools Sequence object

	Returns the centroid file name and cluster file name (from CD-HIT).
	If ::make_db:: is True, a SQLite3 connection and database path are also returned.
	'''
	start_time = time.time()
	seqs = [Sequence(s) for s in seqs]
	if not out_file:
		out_file = tempfile.NamedTemporaryFile(dir=temp_dir, delete=False)
		ofile = out_file.name
	else:
		ofile = os.path.expanduser(out_file)
	ifile = _make_cdhit_input(seqs, temp_dir)
	cdhit_cmd = 'cd-hit -i {} -o {} -c {} -n 5 -d 0 -T 0 -M 35000'.format(ifile, ofile, threshold)
	cluster = sp.Popen(cdhit_cmd, shell=True, stdout=log)
	cluster.communicate()
	os.unlink(ifile)
	logger.info('CD-HIT: clustered {} sequences in {:.2f} seconds'.format(len(seqs),
																   time.time() - start_time))
	cfile = ofile + '.clstr'
	if make_db:
		seq_db, db_path = _build_seq_db(seqs, temp_dir=temp_dir)
		return ofile, cfile, seq_db, db_path
	return ofile, cfile


def parse_centroids(centroid_file):
	'''
	Parses a CD-HIT centroid file (which is just a FASTA file).

	Returns a list of Sequence objects.
	'''
	return [Sequence(s) for s in SeqIO.parse(open(centroid_file, 'r'), 'fasta')]


def parse_clusters(clust_file, seq_db=None):
	'''
	Parses clustered sequences.

	Inputs are a CD-HIT cluster file (ends with '.clstr') and, optionally a connection to a
	SQLite3 database of sequence IDs and sequences.

	Returns a nested list of sequence IDs (one list per cluster) or, if ::seq_db:: is provided,
	a nested list of Sequence objects (a list of Sequence objects for each cluster).
	'''
	raw_clusters = [c.split('\n') for c in open(clust_file, 'r').read().split('\n>')]
	ids = []
	for rc in raw_clusters:
		ids.append(_get_cluster_ids(rc))
	if seq_db is None:
		return ids
	return [_get_cluster_seqs(c) for c in ids]


def _chunker(l, size=900):
	return (l[pos:pos + size] for pos in xrange(0, len(l), size))


def _get_cluster_seqs(seq_ids, seq_db):
	seqs = []
	for chunk in _chunker(seq_ids):
		seq_chunk = seq_db.execute('''SELECT seqs.id, seqs.sequence
								   FROM seqs
								   WHERE seqs.id IN ({})'''.format(','.join('?' * len(chunk))), chunk)
		seqs.extend(seq_chunk)
	return [Sequence(s) for s in seqs]


def _get_cluster_ids(cluster):
	ids = []
	for c in cluster[1:]:
		if c:
			ids.append(c.split()[2][1:-3])
	return ids


def _make_cdhit_input(seqs, temp_dir):
	ifile = tempfile.NamedTemporaryFile(dir=temp_dir, delete=False)
	fastas = [s.fasta() for s in seqs]
	ifile.write('\n'.join(fastas))
	ifile.close()
	return ifile.name


def _build_seq_db(seqs, direc=None):
	'''
	Builds a SQLite3 database of sequences.

	Inputs are a list of Sequence objects and an optional directory to store the database.
	If ::direc:: is not provided, '/tmp' will be used.

	Returns a SQLite3 connection object and the database path.
	'''
	direc = direc if direc else '/tmp'
	db_path = os.path.join(direc, 'seq_db')
	conn = sqlite3.connect(db_path)
	c = conn.cursor()
	create_cmd = '''CREATE TABLE seqs (id text, sequence text)'''
	insert_cmd = 'INSERT INTO seqs VALUES (?,?)'
	c.execute('DROP TABLE IF EXISTS seqs')
	c.execute(create_cmd)
	c.executemany(insert_cmd, [(s.id, s.sequence) for s in seqs])
	c.execute('CREATE INDEX seq_index ON seqs (id)')
	return c, db_path
