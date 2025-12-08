import cast_upgrade_1_6_23 # @UnusedImport
from cast.application import ApplicationLevelExtension, open_source_file, CustomObject, create_link, Bookmark
import logging, shlex, traceback
from collections import defaultdict


class Extension(ApplicationLevelExtension):
    
    def __init__(self):
        self.datasets_loaded = False
        self.datasets = {}
        self.dataset_folder = None
        

    def end_application_create_objects(self, application):
        """
        @type application:cast.application.Application
        """
        for o in application.objects().has_type('CAST_JCL_RootDirectory'):
            if o.get_name() == 'DataSets':
                self.dataset_folder = o
                break
        
        logging.info(str(self.dataset_folder))
        
        self.ftp(application)
        self.cdsend(application)
        
    def ftp(self, application):
        logging.info('Scanning JCL for FTP')

        ftp_callees = application.objects().has_type([
            'JCL_PROGRAM',
            'CAST_COBOL_UtilityProgram',
            'CAST_COBOL_ProgramPrototype',
            'CAST_JCL_CatalogedProcedure',
            'CAST_JCL_ProcedurePrototype'
        ])

        ftps = []
        for o in ftp_callees:
            if o.get_name().upper() == 'FTP':
                ftps.append(o)
        
        if not ftps:
            logging.info('No usage of FTP')
            return

        # force loading of datasets
        self.load_datasets(application)

        logging.info('Scanning JCL...')
        for link in application.links().load_positions()\
                    .has_caller(application.objects().has_type("CAST_JCL_Step"))\
                    .has_callee(ftps):

            positions = link.get_positions()
            if not positions:
                continue

            try:
                step = link.get_caller()
                bookmark_pos = positions[0]
                # @type bookmark_pos:Bookmark
                bookmark_code = bookmark_pos.get_code()
                
                line_number = 0
                for code_line in bookmark_code.splitlines():
                    
                    stripped = code_line.strip()
                    
                    if stripped.lower().startswith('get ') or stripped.lower().startswith('put '):
                        tokens = shlex.split(code_line)
                        if len(tokens) <= 1:
                            continue
                        
                        link_type = 'accessReadLink'
                        
                        dataset_names = []
                        for token in tokens:
                            if token.startswith('//DD:'):
                                continue
                            if token == '+':
                                continue
                            if token == 'GET':
                                # download
                                link_type = 'accessWriteLink'
                                continue
                            if token == 'PUT':
                                # upload
                                link_type = 'accessReadLink'
                                continue
                                
                            dataset_names.append(token)
    
                        logging.info("tokens:" + str(dataset_names))

                        bookmark = Bookmark(bookmark_pos.file,
                                            bookmark_pos.begin_line + line_number,
                                            1,
                                            bookmark_pos.begin_line + line_number,
                                            len(code_line)
                                            )

                        for name in dataset_names:
                            pass
                            dataset = self.get_or_create_dataset(name, step)
                            create_link(link_type, step, dataset, bookmark)
                        
                    line_number += 1
            except:
                logging.warning(traceback.format_exc())

    def cdsend(self, application):
        
        logging.info('Searching CDSEND...')
        
        application.objects().has_type([
            'CAST_JCL_ProcedurePrototype',
            'CAST_JCL_CatalogedProcedure',
        ])

        cdsends = []
        for o in application.objects().has_type(['CAST_JCL_ProcedurePrototype',
                                                 'CAST_JCL_CatalogedProcedure',]):
            if o.get_name().upper() == 'CDSEND':
                cdsends.append(o)
        
        if not cdsends:
            logging.info('No usage of CDSEND')
            return

        self.load_datasets(application)
        
        for link in application.links().load_positions() \
                .has_caller(application.objects().has_type("CAST_JCL_Step")) \
                .has_callee(cdsends):
        
            try:
                positions = link.get_positions()
                if not positions:
                    continue
        
                step = link.get_caller()
                bookmark_pos = positions[0]
                # @type bookmark_pos:Bookmark
                bookmark_code = bookmark_pos.get_code()
                
                current_dsn = None
                current_dsn_begin_line = None
                
                line_number = -1
                for code_line in bookmark_code.splitlines():
                    
                    line_number += 1
                    
                    if code_line.startswith('//*'):
                        continue # comment line
                    
                    stripped = code_line.strip()
                    
                    if stripped.startswith('&&DSN'):
                        if current_dsn:
                            # ends previously started dsn
                            logging.info('Creating dataset ' + current_dsn)
                            logging.info('at line ' + str(bookmark_pos.begin_line + current_dsn_begin_line))
                            dataset = self.get_or_create_dataset(current_dsn, step)
                            bookmark = Bookmark(bookmark_pos.file,
                                                bookmark_pos.begin_line + current_dsn_begin_line,
                                                1,
                                                bookmark_pos.begin_line + current_dsn_begin_line,
                                                len(code_line)
                                                )
                            create_link('accessLink', step, dataset, bookmark)
                            current_dsn = None
                            
                        if stripped.endswith('-'):
                            # continuation
                            current_dsn = stripped[7:-1].strip()
                            current_dsn_begin_line = line_number
                        else:
                            current_dsn = stripped[7:]
                            logging.info('Creating dataset ' + current_dsn)
                            logging.info('at line ' + str(bookmark_pos.begin_line + line_number))
                            dataset = self.get_or_create_dataset(current_dsn, step)
                            bookmark = Bookmark(bookmark_pos.file,
                                                bookmark_pos.begin_line + line_number,
                                                1,
                                                bookmark_pos.begin_line + line_number,
                                                len(code_line)
                                                )
                            create_link('accessLink', step, dataset, bookmark)
                            current_dsn = None                         
                    elif current_dsn:
                        if stripped.endswith('-'):
                            # continuation
                            current_dsn += stripped[:-1].strip()
                        else:
                            # ending
                            current_dsn += stripped
                            logging.info('Creating dataset ' + current_dsn)
                            logging.info('at line ' + str(bookmark_pos.begin_line + current_dsn_begin_line))
                            dataset = self.get_or_create_dataset(current_dsn, step)
                            bookmark = Bookmark(bookmark_pos.file,
                                                bookmark_pos.begin_line + current_dsn_begin_line,
                                                1,
                                                bookmark_pos.begin_line + current_dsn_begin_line,
                                                len(code_line)
                                                )
                            create_link('accessLink', step, dataset, bookmark) 
                            current_dsn = None                          
                        
            except:
                logging.warning(traceback.format_exc())
        

    def load_datasets(self, application):
        
        if self.datasets_loaded:
            return # only once
        
        logging.info('Loading datasets...')
        for dataset in application.objects().has_type('CAST_JCL_ResolvedDataset'):
            self.datasets[dataset.get_name()] = dataset
        
        self.datasets_loaded = True
        
    def get_or_create_dataset(self, name, step):
        
        try:
            return self.datasets[name]
        except KeyError:
            # create
            dataset = CustomObject()
            dataset.set_name(name)
            dataset.set_type('FTP_Unknown_JCL_Dataset')
            if self.dataset_folder:
                dataset.set_parent(self.dataset_folder)
            else:
                dataset.set_parent(step)
            dataset.save()
            # for next time
            self.datasets[name] = dataset
            return dataset
            
            