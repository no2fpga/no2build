#!/usr/bin/env python3
#
# Each LUT that goes to several FF can be duplicated to gain some LCs.
#
# Copyright (C) 2020 Sylvain Munaut
# SPDX-License-Identifier: MIT
#


def run_opt(ctx):

	cnt_grp = 0
	cnt_new = 0

	for cn, ci in ctx.cells:
		# Only look at lut4
		if ci.type != 'SB_LUT4':
			continue

		# Scan users
		ff = []
		other = False
		for u in ci.ports['O'].net.users:
			# If we have any other users than D port on DFFs, then it's no use
			if (not u.cell.type.startswith('SB_DFF')) or (u.port != 'D'):
				other = True
				break

			ff.append(u)

		# Should we do duplication ?
		if other or len(ff) < 2:
			continue

		# Count
		cnt_grp += 1
		cnt_new += len(ff) - 1

		# Duplicate as needed
		for i,d in enumerate(ff[1:]):
			# Get previous data
			on = ci.ports['O'].net

			# New Cell
			nc = ctx.createCell(ci.name + '_dup' + str(i), 'SB_LUT4')

				# Copy inputs
			for pn in ['I0', 'I1', 'I2', 'I3']:
				if pn not in ci.ports:
					continue
				nc.addInput(pn)
				if ci.ports[pn] is None:
					continue
				ctx.connectPort(ci.ports[pn].net.name, nc.name, pn)

				# Create output
			nc.addOutput('O')

				# Copy config
			for an,av in ci.attrs:
				nc.setAttr(an,av)
			for pn,pv in ci.params:
				nc.setParam(pn,pv)

			# Rewire
			ctx.disconnectPort(d.cell.name, 'D')

			nn = ctx.createNet(on.name + '_dup' + str(i))
			ctx.connectPort(nn.name, d.cell.name, 'D')
			ctx.connectPort(nn.name, nc.name, 'O')

	print("LUT replication: %d new LUTs in %d groups" % (cnt_new, cnt_grp))
