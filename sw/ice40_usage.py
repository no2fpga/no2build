#!/usr/bin/env python3
#
# Show usage post-pack
#
# Copyright (C) 2020 Sylvain Munaut
# SPDX-License-Identifier: MIT
#

CELLS = {
	'ICESTORM_LC':    (   'LC', 5),
	'ICESTORM_RAM':   (  'RAM', 2),
	'ICESTORM_DSP':   (  'DSP', 1),
	'ICESTORM_SPRAM': ('SPRAM', 1),
}


class UsageTracker:

	def __init__(self):
		self.usage = {}

	def add_cell(self, c):
		# Only count cell we're interested in
		if c.type not in CELLS:
			return

		# Path & element name
		path = c.name.split('.')
		en = '_' + c.type

		# Add usage  at every level
		b = self.usage

		for i, c in enumerate(path):
			# Update self current usage
			n_self, n_sub = b.setdefault(en, (0, 0))
			if i == len(path) - 1:
				n_self += 1
			n_sub += 1
			b[en] = (n_self, n_sub)

			# Sub
			if i != len(path) - 1:
				b = b.setdefault(c, {})

	def print(self):
		# Print header
		ct = []
		hdr1 = []
		hdr2 = []

		for cfn, (cn, cl) in CELLS.items():
			l = max(2 + len(cn), 2*cl+3)
			ct.append( (cfn, cl, l-(2*cl+3)) )
			hdr1.append(' %s%s ' % (cn, ' ' * (l-2-len(cn))))
			hdr2.append('-' * l)

		hdr1.append(' Path')
		hdr2.append(20*'-')

		print('|'.join(hdr1))
		print('|'.join(hdr2))

		self._print(self.usage, '/', 0, ct)

	def _print(self, usage, name, lvl, ct):
		# Print usage of this node
		p = '  ' * lvl + name
		l = []

		for cn, cl, pl in ct:
			p1 = ' ' * ( pl    // 2)
			p2 = ' ' * ((pl+1) // 2)
			f = ' %s%%%dd/%%%dd%s ' % (p1, cl, cl, p2)
			u = usage.get('_'+cn, (0,0))
			l.append(f % u)

		l.append(' ' + p)

		print('|'.join(l))

		# Scan sub nodes
		for k, v in usage.items():
			if k.startswith('_'):
				continue
			self._print(v, k, lvl+1, ct)


# Process all cells in design
ut = UsageTracker()

for cn, c in ctx.cells:
	ut.add_cell(c)

ut.print()
