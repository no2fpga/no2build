#!/usr/bin/env python3
#
# Attempts to optimizat Control Sets and remove those that have very
# low usage
#
# Copyright (C) 2020 Sylvain Munaut
# SPDX-License-Identifier: MIT
#

from collections import namedtuple


#
# TODO: When evaluating cost and wiring stuff, if the signal of the control set
# happen to be already existing on the LUT, it could be used ...
#


class ControlSet(namedtuple('ControlSet', 'rs ena clk')):

	__slots__ = []

	@classmethod
	def from_cell(kls, cell):
		if not cell.type.startswith('SB_DFF'):
			raise ValueError("Invalid cell type")

		net_r = cell.ports['R'].net.name if (('R' in cell.ports) and (cell.ports['R'].net is not None)) else None
		net_s = cell.ports['S'].net.name if (('S' in cell.ports) and (cell.ports['S'].net is not None)) else None
		net_e = cell.ports['E'].net.name if (('E' in cell.ports) and (cell.ports['E'].net is not None)) else None
		net_c = cell.ports['C'].net.name if (('C' in cell.ports) and (cell.ports['C'].net is not None)) else None

		return kls(net_r or net_s, net_e, net_c)


class ControlSetOptimizer:

	def __init__(self, ctx):
		self.ctx = ctx

		self.global_nets = self.find_global_nets()
		self.cset_map = self.build_map()

	def find_global_nets(self):
		"""List all nets (names) that are output from global buffers"""
		return set([
			c[1].ports['GLOBAL_BUFFER_OUTPUT'].net.name
				for c in self.ctx.cells
				if c[1].type=='SB_GB'
		])

	def build_map(self):
		# Init
		cset_map = {}

		# Scan all cells
		for cell_name, cell in self.ctx.cells:
			# Only consider FFs
			if not cell.type.startswith('SB_DFF'):
				continue

			# Add cell
			cset = ControlSet.from_cell(cell)
			cset_map.setdefault(cset, []).append(cell)

		return cset_map

	def stats(self):
		"""Print some statistics"""

		print(f"Total control sets: {len(self.cset_map):d}")
		csl = {}
		for k, v in self.cset_map.items():
			csl.setdefault(len(v), []).append( (k, v) )

		for k, v in sorted(csl.items(), key=lambda x: x[0]):
			print(k, len(v))

		for k, v in sorted(self.cset_map.items(), key=lambda x: len(x[1])):
			print(len(v), k)

	# Utility
	def _net_name_simplify(self, net):
		if net is None:
			return None
		if net.driver.cell.type in ['GND', 'VCC']:
			return net.driver.cell.type
		return net.name

	def _unused_port(self, cell, port_name):
		n = cell.ports[port_name].net
		if n is None:
			return True

			# Technically a fixed 'VCC' connection could be removed too
			# but the _update_lut_init assumes unused ports were zero.
			# Also, VCC is only used if there is a damn good reason, like
			# needed for a SB_CARRY ...
		if n.driver.cell.type == 'GND':
			return True

		return False

	def _cell_has_carry(self, cell):
		# Get connections to 'I1' and 'I2'
		n1 = cell.ports['I1'].net
		n2 = cell.ports['I2'].net

		users = (list(n1.users) if n1 else []) + (list(n2.users) if n2 else [])

		nn1 = self._net_name_simplify(n1)
		nn2 = self._net_name_simplify(n2)

		for u in users:
			if u.cell.type != 'SB_CARRY':
				continue
			if self._net_name_simplify(u.cell.ports['I0'].net) != nn1:
				continue
			if self._net_name_simplify(u.cell.ports['I1'].net) != nn2:
				continue
			return True

		return False

	def _lut_free_ports(self, cell):
		# First pass
		free_ports = [ p
			for p in ['I0', 'I1', 'I2', 'I3']
			if self._unused_port(cell, p)
		]

		# If the cell has a carry out attached ... remove I1/I2
		if self._cell_has_carry(cell):
			for p in ['I1', 'I2']:
				if p in free_ports:
					free_ports.remove(p)

		return free_ports

	def cost_convert(self, cset, conv):
		# Init
		rm_rs  = bool(conv & 1)
		rm_ena = bool(conv & 2)

		n_in = (2 * rm_ena) + (1 * rm_rs)
		cost = 0

		# Scan all cells in that set
		for cell in self.cset_map[cset]:
			# Get cell driving that FF
			driver_cell = cell.ports['D'].net.driver.cell

			# If it's not a LUT already, then we can put a LUT in front for free, always
			if driver_cell.type != 'SB_LUT4':
				continue

			# If there is more than one user of the LUT, we always need a new one
			# and it comes for free since it wouldn't have been packable in the same LC
			# anyway
			if len(driver_cell.ports['O'].net.users) > 1:
				continue

			# Count how many LUT inputs are 'free'
			free_ports = self._lut_free_ports(driver_cell)
			if len(free_ports) < n_in:
				cost = cost + 1

		# Return cost of conversion
		return cost

	def can_convert(self, cset, conv):
		# What do we want to remove
		rm_rs  = bool(conv & 1)
		rm_ena = bool(conv & 2)

		# What do we have
		has_rs  = (cset.rs  is not None) # and (cset.rs  not in self.global_nets)
		has_ena = (cset.ena is not None) # and (cset.ena not in self.global_nets)

		# If the reset is used for asynchronous set/reset, we can't remove it
		if has_rs:
			for c in self.cset_map[cset]:
				if c.type in ['SB_DFFR', 'SB_DFFS', 'SB_DFFER', 'SB_DFFES']:
					has_rs = False
					break

		# Does that conversion make sense
		if rm_rs and not has_rs:
			return False
		if rm_ena and not has_ena:
			return False

		# If we remove an ENA and there is a reset, that can be an issue because ENA
		# has precedence ...

		# FIXME:
		# If the 'has_xxx' above excludes global nets, then this check kind of
		# consider that 'global' resets have precedence which is not true in hardware :/
		# We could check the generation of the ena signal to see if having rs=1 implies
		# ena=1 but that's quite a bit of logic to do that ...
		if has_rs and (rm_ena and not rm_rs):
			return False

		return True

	def exec_convert(self, cset, conv):
		# What do we want to remove
		rm_rs  = bool(conv & 1)
		rm_ena = bool(conv & 2)
		n_in   = (2 * rm_ena) + (1 * rm_rs)

		# Update every cell
		for cell in self.cset_map[cset]:
			# Disconnect from FF and adapt cell type
			t = cell.type
			set_reset = 'SS' in t

			has_rs = ('SR' in t) or ('SS' in t)

			if rm_rs:
				self.ctx.disconnectPort(cell.name, 'R')
				self.ctx.disconnectPort(cell.name, 'S')
				t = t.replace('SR', '').replace('SS', '')

			if rm_ena:
				self.ctx.disconnectPort(cell.name, 'E')
				t = t.replace('E', '')

			cell.type = t

			# Get cell driving that FF
			driver_cell = cell.ports['D'].net.driver.cell

			# If it's not a LUT, we need to insert a lut ...
			# If it is, we collect free ports
			# Also need to check that LUT is only used once !
			free_ports = []

			if (driver_cell.type == 'SB_LUT4') and (len(driver_cell.ports['O'].net.users) == 1):
				free_ports = self._lut_free_ports(driver_cell)

			# Do we need a new lut or alter the existing one ?
			if len(free_ports) < n_in:
				# Insert a new LUT
				new_lut = self.ctx.createCell(cell.name + '_conv', 'SB_LUT4')
				new_lut.addInput('I0')
				new_lut.addInput('I1')
				new_lut.addInput('I2')
				new_lut.addInput('I3')
				new_lut.addOutput('O')
				new_lut.setParam('LUT_INIT', '1111111100000000')

				# New net
				new_net = self.ctx.createNet(cell.name + '_net')

				# Interpose out new LUT
				old_net = cell.ports['D'].net

				self.ctx.disconnectPort(cell.name, 'D')
				self.ctx.connectPort(old_net.name, new_lut.name, 'I3')
				self.ctx.connectPort(new_net.name, new_lut.name, 'O')
				self.ctx.connectPort(new_net.name, cell.name, 'D')

				# Freeports on this lut
				tgt_lut = new_lut
				free_ports = ['I0', 'I1', 'I2']

			else:
				tgt_lut = driver_cell

			# Connect target LUT
			if rm_rs:
				# Assign port
				p_rs  = free_ports.pop()
				pn_rs = int(p_rs[1:])

				# Connect signals
				self.ctx.disconnectPort(tgt_lut.name, p_rs)
				self.ctx.connectPort(cset.rs, tgt_lut.name, p_rs)
			else:
				pn_rs = None

			if rm_ena:
				# Assign port
				p_ena  = free_ports.pop()
				pn_ena = int(p_ena[1:])
				p_old  = free_ports.pop()
				pn_old = int(p_old[1:])

				# Connect signals
				self.ctx.disconnectPort(tgt_lut.name, p_ena)
				self.ctx.disconnectPort(tgt_lut.name, p_old)
				self.ctx.connectPort(cset.ena, tgt_lut.name, p_ena)
				self.ctx.connectPort(cell.ports['Q'].net.name, tgt_lut.name, p_old)
			else:
				pn_ena = None
				pn_old = None

			# Modify LUT content
			tgt_lut.setParam('LUT_INIT', self._update_lut_init(
				tgt_lut.params['LUT_INIT'],
				pn_rs, set_reset,
				pn_ena, pn_old
			))

			# Connect remaining free ports to 'GND' if they're still unconnected
			# FIXME

	def _update_lut_init(self, val, pn_rs, rs_val, pn_ena, pn_old):
		# Convert value to int
		val = int(val, 2)

		# Scan all bits
		for i in range(16):
			mask = 1 << i

			# Handle reset/set
			if (pn_rs is not None) and (i & (1 << pn_rs)):
				if rs_val:
					# Set bit
					val |=  mask
				else:
					# Clear bit
					val &= ~mask

			# Handle enable
			if (pn_ena is not None) and not (i & (1 << pn_ena)):
				if (i & (1 << pn_old)):
					# Set bit
					val |=  mask
				else:
					# Clear bit
					val &= ~mask

		# Convert value back
		return f'{val:016b}'

	def optimize(self, threshold=4, debug=False):
		# Init loop
			# Sort to be consistent across run ...
		to_process = sorted(self.cset_map.keys(), key=lambda x: (x[0] or '', x[1] or '', x[2] or ''))
		cset_cnt_before = len(self.cset_map)
		total_cost = 0

		# Process while there are control sets in the pool
		while len(to_process):
			# Pick one
			cset = to_process.pop()
			cells = self.cset_map[cset]

			# Don't bother trying to consolidate sets that are well used
			if len(cells) >= threshold:
				continue

			# We can remove RS,E or both. Evaluate result and cost for all 3
			possible_tgt = []

			for conv in range(1,4):
				# Make sure that option makes senses
				if not self.can_convert(cset, conv):
					continue

				# What do we want to remove
				rm_rs  = bool(conv & 1)
				rm_ena = bool(conv & 2)

				tgt = ControlSet(
					None if rm_rs  else cset.rs,
					None if rm_ena else cset.ena,
					cset.clk
				)

				# Number of cells in potential resulting group
				cell_in_group = len(cells)
				cset_in_group = [ cset ]

				# Does that create a resulting control set that already exists ?
				if tgt in self.cset_map:
					cell_in_group += len(self.cset_map[tgt])

				# Maybe applying the same conversion to other control set would bring them in-line
				if tgt.rs or tgt.ena:
					for alt_cset in to_process:
						# Possible alt targets
						alt_cells = self.cset_map[alt_cset]
						alt_tgt = ControlSet(
							None if rm_rs  else alt_cset.rs,
							None if rm_ena else alt_cset.ena,
							alt_cset.clk
						)

						# Only consider low-cell control sets
						if len(alt_cells) >= threshold:
							continue

						# Only consider conversion that make sense
						if not self.can_convert(alt_cset, conv):
							continue

						# Check it's a match
						if tgt == alt_tgt:
							# Ok, that's a possibility count possible cells in resulting group
							cell_in_group += len(alt_cells)
							cset_in_group.append(alt_cset)

				# If at this point, we don't have enough, discard that option
				if cell_in_group < threshold:
					continue

				# Record result
				cost = sum( [self.cost_convert(x, conv) for x in cset_in_group] )
				possible_tgt.append( (tgt, conv, cost, cell_in_group, cset_in_group) )

			# Nothing to do ?
			if len(possible_tgt) == 0:
				continue

			# Select the option that yields the lower cost per removed control set
			possible_tgt = sorted(possible_tgt, key=lambda x: (x[2] / len(x[4]), -x[3]))

			if debug:
				for tgt, conv, cost, cell_in_group, cset_in_group in possible_tgt:
					print("%d %d %r" % (cost, cell_in_group, tgt))
					for x in cset_in_group:
						print("     %2d %r" % (len(self.cset_map[x]),x))
				print("--------------")

			tgt, conv, cost, cell_in_group, cset_in_group = possible_tgt[0]

			# Process
			for cset_cur in cset_in_group:
				# Apply conversion
				self.exec_convert(cset_cur, conv)

				# Update state variable
				if cset_cur in to_process:
					to_process.remove(cset_cur)

				cells_cur = self.cset_map.pop(cset_cur)
				self.cset_map.setdefault(tgt,[]).extend(cells_cur)

			total_cost += cost

		cset_cnt_after = len(self.cset_map)

		print("Control Set Optimizer: cost %d to reduce control sets from %d to %d" % (total_cost, cset_cnt_before, cset_cnt_after))


def run_opt(ctx, threshold=4, debug=False):
	debug = True
	opt = ControlSetOptimizer(ctx)
	opt.optimize(threshold=threshold, debug=debug)
	if debug:
		opt.stats()
