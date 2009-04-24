# Copyright (c) 2007-2009 PediaPress GmbH
# See README.txt for additional licensing information.

"""mw-render -- installed via setuptools' entry_points"""

import os
import sys
import errno
import pkg_resources
from mwlib.options import OptionParser
from mwlib import utils, wiki

class Main(object):
    zip_filename = None
    
    def parse_options(self):
        parser = OptionParser(config_optional=True)
        parser.add_option("-o", "--output", help="write output to OUTPUT")
        parser.add_option("-w", "--writer", help='use writer backend WRITER')
        parser.add_option("-W", "--writer-options",
            help='";"-separated list of additional writer-specific options',
        )
        parser.add_option("-e", "--error-file", help='write errors to this file')
        parser.add_option("-s", "--status-file",
            help='write status/progress info to this file',
        )
        parser.add_option("--list-writers",
            action='store_true',
            help='list available writers and exit',
        )
        parser.add_option("--writer-info",
            help='list information about given WRITER and exit',
            metavar='WRITER',
        )
        parser.add_option('--keep-zip',
            help='write ZIP file to FILENAME',
            metavar='FILENAME',
        )
        parser.add_option('--keep-tmpfiles',                  
            action='store_true',
            default=False,
            help="don't remove  temporary files like images",
        )
        parser.add_option('-L', '--language',
            help='use translated strings in LANGUAGE',
        )
        parser.add_option('-f', '--fastzipcreator',
            help='Use experimental new fzipcreator code',
            action='store_true',
        )
        options, args = parser.parse_args()
        return options, args, parser
    
    def load_writer(self, name):
        try:
            entry_point = pkg_resources.iter_entry_points('mwlib.writers', name).next()
        except StopIteration:
            sys.exit('No such writer: %r (use --list-writers to list available writers)' % name)
        try:
            return entry_point.load()
        except Exception, e:
            sys.exit('Could not load writer %r: %s' % (name, e))

    def list_writers(self):
        for entry_point in pkg_resources.iter_entry_points('mwlib.writers'):
            try:
                writer = entry_point.load()
                if hasattr(writer, 'description'):
                    description = writer.description
                else:
                    description = '<no description>'
            except Exception, e:
                description = '<NOT LOADABLE: %s>' % e
            print '%s\t%s' % (entry_point.name, description)

    def show_writer_info(self, name):
        writer = self.load_writer(name)
        if hasattr(writer, 'description'):
            print 'Description:\t%s' % writer.description
        if hasattr(writer, 'content_type'):
            print 'Content-Type:\t%s' % writer.content_type
        if hasattr(writer, 'file_extension'):
            print 'File extension:\t%s' % writer.file_extension
        if hasattr(writer, 'options') and writer.options:
            print 'Options (usable in a ";"-separated list for --writer-options):'
            for name, info in writer.options.items():
                param = info.get('param')
                if param:
                    print ' %s=%s:\t%s' % (name, param, info['help'])
                else:
                    print ' %s:\t%s' % (name, info['help'])

    def get_environment(self):
        from mwlib.status import Status
        from mwlib import zipwiki, nuwiki
        
        if self.options.fastzipcreator:
            from mwlib import fzipcreator as zipcreator
        else:
            from mwlib import zipcreator
            
        env = self.parser.makewiki()        
        if ((isinstance(env.wiki, zipwiki.Wiki) and isinstance(env.images, zipwiki.ImageDB))
            or isinstance(env.wiki, (nuwiki.nuwiki, nuwiki.adapt))):
            self.status = Status(self.options.status_file, progress_range=(0, 100))
            return env

        from mwlib.apps.buildzip import hack
        self.zip_filename = hack(options=self.options, env=env, podclient=None, status=self.status)
        # FIXME: keep zip ???
        
        
        if env.images:
            try:
                env.images.clear()
            except OSError, err:
                if err.errno!=errno.ENOENT:
                    raise
                
        env = wiki.makewiki(self.zip_filename)
        self.status = Status(self.options.status_file, progress_range=(71, 100))
        return env
            
        
    def __call__(self):    
        options, args, parser = self.parse_options()
        self.parser = parser
        self.options = options
        
        import tempfile
        from mwlib.mwapidb import MWAPIError
        from mwlib.writerbase import WriterError
        from mwlib.status import Status

        use_help = 'Use --help for usage information.'


        if options.list_writers:
            self.list_writers()
            return

        if options.writer_info:
            self.show_writer_info(options.writer_info)
            return
        

        if options.config is None:
            parser.error('Please specify --config.\n' + use_help)

        if options.output is None:
            parser.error('Please specify an output file with --output.\n' + use_help)

        options.output = os.path.abspath(options.output)

        if options.writer is None:
            parser.error('Please specify a writer with --writer.\n' + use_help)    

        writer = self.load_writer(options.writer)
        writer_options = {}
        if options.writer_options:
            for wopt in options.writer_options.split(';'):
                if '=' in wopt:
                    key, value = wopt.split('=', 1)
                else:
                    key, value = wopt, True
                writer_options[key] = value
        if options.language:
            writer_options['lang'] = options.language
        for option in writer_options.keys():
            if option not in getattr(writer, 'options', {}):
                print 'Warning: unknown writer option %r' % option
                del writer_options[option]

        if options.daemonize:
            utils.daemonize()
        if options.pid_file:
            open(options.pid_file, 'wb').write('%d\n' % os.getpid())

        self.status = status = Status(options.status_file, progress_range=(1, 70))
        status(progress=0)

        env = None
        try:
            try:
                env = self.get_environment()
                
                fd, tmpout = tempfile.mkstemp(dir=os.path.dirname(options.output))
                os.close(fd)
                writer(env, output=tmpout, status_callback=status, **writer_options)
                os.rename(tmpout, options.output)
                kwargs = {}
                if hasattr(writer, 'content_type'):
                    kwargs['content_type'] = writer.content_type
                if hasattr(writer, 'file_extension'):
                    kwargs['file_extension'] = writer.file_extension
                status(status='finished', progress=100, **kwargs)
                if options.keep_zip is None and self.zip_filename is not None:
                    utils.safe_unlink(self.zip_filename)
            except Exception, e:
                import traceback
                status(status='error')
                if options.error_file:
                    fd, tmpfile = tempfile.mkstemp(dir=os.path.dirname(options.error_file))
                    f = os.fdopen(fd, 'wb')
                    if isinstance(e, (WriterError, MWAPIError)):
                        f.write(str(e))
                    else:
                        f.write('traceback\n')
                        traceback.print_exc(file=f) 
                    f.close()
                    os.rename(tmpfile, options.error_file)
                raise
        finally:
            if env is not None and env.images is not None:
                try:
                    if not options.keep_tmpfiles:
                        env.images.clear()
                except OSError, e:
                    if e.errno!=errno.ENOENT:
                        print 'ERROR: Could not remove temporary images: %s' % e, e.errno
            if options.pid_file:
                utils.safe_unlink(options.pid_file)

def main():
    return Main()()