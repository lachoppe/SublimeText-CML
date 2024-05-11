import sublime
import sublime_plugin
import re
import weakref

abortPlugin = 0
debugLevel = 0

def indent(line):
    strip = line.lstrip()
    return len(line) - len(strip)

def errorMessage(msg, num, text):
	global abortPlugin
	abortPlugin = 1
	sublime.error_message( "Syntax error!  Aborting...\n\n{0}\n{1}: {2}".format( msg, num, text ) )

def debugOut(msg, content, line, level):
	if debugLevel >= level:
		print( "{0}: {1}: {2}".format( line, msg, content) )

class Node(object):

	def __init__( self ):
		self.parent = None
		self.indent = 0
		self.text = ""
		self.errorLine = 0
		self.live = -1
		self.active = 0
		self.bug = 0
		self.children = []

	def setParent( self, parent ):
		self.parent = weakref.ref( parent ) if parent else None

	def addChild( self, node ):
		self.children.append( node )

	def printTree( self ):
		text = self.text
		prefix = "-" if self.live else "+"
		print (prefix, text.rstrip())
		for c in self.children:
			c.printTree()

	def hasDeadPath( self ):
		if self.live == 1:
			return 0
		if len( self.children ) == 0:
			return 1
		valid = 0
		for c in self.children:
			valid = valid or c.hasDeadPath()
		return valid

	def compileDeadTree( self, sum ):
		if self.hasDeadPath():
			debugOut("dead path", self.text, self.errorLine, 2) 
			sum += self.text
			for c in self.children:
				sum = c.compileDeadTree( sum )
		return sum

	def hasLivePath( self ):
		if len( self.children ) == 0:
			return self.live
		valid = self.live
		for c in self.children:
			valid = valid or c.hasLivePath()
		return valid

	def compileLiveTree( self, sum, force ):
		if force or self.hasLivePath():
			debugOut("live path", self.text, self.errorLine, 2)
			sum += self.text
			for c in self.children:
				sum = c.compileLiveTree( sum, force or self.live )
		return sum

	def hasActivePath( self ):
		if len( self.children ) == 0:
			return self.active
		valid = self.active
		for c in self.children:
			valid = valid or c.hasActivePath()
		return valid

	def hasBugPath( self ):
		if len( self.children ) == 0:
			return self.bug
		valid = self.bug
		for c in self.children:
			valid = valid or c.hasBugPath()
		return valid

class Section(object):
	def __init__(self):
		self.nodes = []
		self.header = ""
		self.bugs = ""
		self.active = ""
		self.text = ""

	def commit(self, newfile):
		newfile += self.header
		newfile += self.bugs
		newfile += self.active
		newfile += self.text
		return newfile


def makeNode( line, errorLine, parent ):
	node = Node()
	node.indent = indent(line)
	node.text = line
	node.errorLine = errorLine

	node.live = 0
	foundLive = re.search( r'^\s*[-\*!#\?] ', line, re.M )
	if foundLive:
		node.live = 1

	node.active = 0
	foundActive = re.search( r'^\s*\* ', line, re.M )
	if foundActive:
		node.active = 1
		node.live = 1
	node.bug = 0
	if bugsFirst:
		foundBugs = re.search( r'^\s*\# ', line, re.M )
		if foundBugs:
			node.bug = 1
			node.live = 1
	node.setParent( parent )
	if parent != None:
		parent.addChild( node )
	return node


class CmlCleanupCommand(sublime_plugin.TextCommand):
	def run(self, edit):

		settings = sublime.load_settings('cml.sublime-settings')

		debugLevel = settings.get('cml_debug_level', 0)
		global bugsFirst
		bugsFirst = settings.get('cml_bugs_first', 0)

		if debugLevel > 0:
			print("Running CmlCleanup in debug level {0}".format(debugLevel));

		self.view.run_command("select_all")
		allRegion = self.view.sel()[0];

		lineRegions = self.view.split_by_newlines( allRegion )

		# Move done to the end of the file
		# Move bugs to the top of header ranges (if specified)
		# Sort in-progress trees to the top of the section
		# Keep done parents and children in trees with live nodes
		# Done root->leaf path goes to Done section

		newFile = ""
		done = ""
		sections = []

		section = Section()
		lastNode = None

		errorLine = 0

		for region in lineRegions:

			(row,col) = self.view.rowcol( region.a )
			errorLine = row + 1

			line = self.view.line( region )
			lineContents = self.view.substr( line ) + '\n'

			# remove empty lines
			foundEmpty = re.search( r'^\s*$', lineContents, 0 )
			if foundEmpty:
				continue

			# segregate bugs
			if bugsFirst:
				foundBug = re.search( r'^\s*(\# .*)$', lineContents, re.M )
				if foundBug:
					debugOut("found bug", foundBug.group(1), errorLine, 1) 
					section.bugs += foundBug.group(1) + '\n'
					continue

			foundHeader = re.search( r'==', lineContents, re.M )
			if foundHeader:
				# new section
				sections.append( section )
				section = Section()
				lastNode = None

				foundDoneHeader = re.search( r'=== DONE', lineContents, re.I | re.M )
				if foundDoneHeader == None:
					section.header = lineContents + '\n'
				continue

			# add node to tree
			ind = indent( lineContents )
			parent = None
			if ind > 0:
				parent = lastNode
				while parent != None and parent.indent != (ind - 1):
					if parent.indent == 0:
						errorMessage( "parent.indent is 0", errorLine, lineContents )
						return
					parent = parent.parent()  

			if ind != 0 and parent == None:
				errorMessage( "have indent but no parent", errorLine, lineContents )
				return

			node = makeNode( lineContents, errorLine, parent )
			if ind == 0:
				section.nodes.append( node )

			lastNode = node

		if abortPlugin:
			return

		sections.append( section )

		# get the live and dead interpretations of the node trees
		for section in sections:
			for node in section.nodes:
				if debugLevel > 0:
					node.printTree()

				if node.hasActivePath():
					activeTree = node.compileLiveTree( "", 0 )
					section.active += activeTree
				elif node.hasBugPath():
					bugTree = node.compileLiveTree( "", 0 )
					section.bugs += bugTree
				else:
					liveTree = node.compileLiveTree( "", 0 )
					section.text += liveTree

				deadTree = node.compileDeadTree( "" )
				done += deadTree

		if abortPlugin:
			return

		# commit sections to the new file
		for section in sections:
			if len(section.header) == 0:
				continue

			newFile = section.commit( newFile ) + '\n'

		if abortPlugin:
			return

		newFile += '\n=== DONE\n\n'
		newFile += done

		region = sublime.Region(0,self.view.size())
		self.view.replace( edit, region, newFile )

		self.view.sel().clear()

		sublime.status_message('CML Cleanup done.')
