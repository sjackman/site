#!/usr/bin/env python
'''
Create _config.yml used to compile Software Carpentry web site.
'''

import sys
import os
import glob
import datetime
import time
import yaml
from optparse import OptionParser
try:  # Python 3
    from urllib.parse import urlparse, urljoin
except ImportError:  # Python 2
    from urlparse import urlparse, urljoin
from util import CONFIG_YML, \
                 STANDARD_YML, \
                 AIRPORTS_YML, \
                 BADGES_YML, \
                 WORKSHOP_URLS_YML, \
                 WORKSHOP_CACHE, \
                 P_BLOG_EXCERPT, \
                 harvest_metadata, \
                 load_info

# Translate two-digit month identifiers into short names.
MONTHS = {
    '01' : 'Jan', '02' : 'Feb', '03' : 'Mar', '04' : 'Apr',
    '05' : 'May', '06' : 'Jun', '07' : 'Jul', '08' : 'Aug',
    '09' : 'Sep', '10' : 'Oct', '11' : 'Nov', '12' : 'Dec'
}

# Template for recent blog posts.
RECENT_POST = '''\
<h4><a href="{{page.root}}/%(path)s">%(title)s</a></h4>
<small>By %(author)s / <a href="{{page.root}}/%(path)s">%(date)s</a> </small>
<p>
    %(excerpt)s
    <a class="pull-right" href="{{page.root}}/%(path)s">...read more</a>
</p><br /><br />
'''

#----------------------------------------

def main():
    '''
    Main driver for regenerating _config.yml for web site.
    This program also creates _includes/recent_blog_posts.html.
    '''

    # Get the standard stuff.
    options, args = parse_args()

    # Check that a cached workshop information file is available, and
    # report an error if it's not.  Do this early to avoid wasting
    # time; store in local variable until other workshop info is
    # loaded and available for merging.
    cached_workshop_info = load_cached_workshop_info(os.curdir, WORKSHOP_CACHE)

    # Load other information.
    config = load_info(options.config_dir, STANDARD_YML)
    config['badges'] = load_info(options.config_dir, BADGES_YML)
    config['airports'] = load_info(options.config_dir, AIRPORTS_YML)
    config.update({
        'month_names'     : MONTHS,
        'months'          : sorted(MONTHS.keys()),
        'site'            : options.site,
        'timestamp'       : time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'today'           : options.today
    })

    config['people'] = map(lambda x: os.path.relpath(x, '_includes'), 
	sorted(glob.glob('_includes/people/*.html')))

    # Cache the window size.
    recent_length = config['recent_length']
    upcoming_length = config['upcoming_length']

    # Get information from blog entries.
    config['blog'] = harvest_blog(config)

    # Sanity checks on blog posts.
    check_blog_sanity(config['blog'])

    # Select those that'll be displayed on the home page, the index page, etc.
    config['blog_recent'] = config['blog'][-recent_length:]
    config['blog_recent'].reverse()

    # Create _includes/recent_blog_posts.html for inclusion in blog index page.
    # This is done programmatically because we want snippets to be rendered properly.
    for post in config['blog_recent']:
        post['excerpt'] = get_blog_excerpt(post['path'])
    write_recent_blog_posts(config['blog_recent'])

    # Organize all posts by year and month.
    blog_lookup, blog_count = organize_blog_entries(config['blog'])
    config['blog_lookup'] = blog_lookup
    config['blog_count'] = blog_count
    config['blog_years'] = sorted(blog_lookup.keys())
    config['blog_years'].reverse()

    # Construct list of favorite blog posts.
    config['blog_favorites'] = [p for p in config['blog'] if p['favorite']]
    config['blog_favorites'].reverse()

    # Ensure that information about workshops is in the right order.
    cached_workshop_info.sort(lambda x, y: cmp(x['slug'], y['slug']))
    config['workshops'] = cached_workshop_info

    # Select those that'll be displayed on the home page.  Use a loop instead of
    # a list comprehension to get better error reporting.
    upcoming = []
    for bc in config['workshops']:
        try:
            if bc['startdate'] >= config['today']:
                upcoming.append(bc)
        except TypeError, e:
            print >> sys.stderr, 'Unable to process start date "{0}"'.format(bc['startdate'])
    config['workshops_upcoming'] = upcoming[:upcoming_length]
    config['workshops_num_upcoming'] = len(upcoming)

    # Save.
    with open(CONFIG_YML, 'w') as writer:
        yaml.dump(config, writer, encoding='utf-8', allow_unicode=True)

#----------------------------------------

def parse_args():
    '''Parse command-line arguments.'''

    parser = OptionParser()
    parser.add_option('-c', '--config', dest='config_dir', help='configuration directory')
    parser.add_option('-o', '--output', dest='output', help='output directory')
    parser.add_option('-s', '--site', dest='site', help='site')
    parser.add_option('-t', '--today', dest='today', help='build date',
                      default=datetime.date.today())
    parser.add_option('-v', '--verbose', dest='verbose', help='enable verbose logging',
                      default=False, action='store_true')
    options, args = parser.parse_args()
    return options, args

#----------------------------------------

def load_cached_workshop_info(folder, filename):
    '''Load cached workshop info if available, fail if not.'''
    path = os.path.join(folder, filename)
    if not os.path.isfile(path):
        print >> sys.stderr, 'Workshop information cache "{0}" does not exist.'.format(path)
        print >> sys.stderr, 'Please use "make cache" before building site,'
        print >> sys.stderr, 'Or run "bin/get_workshop_info" to regenerate it.'
        sys.exit(1)
    return load_info(folder, filename)

#----------------------------------------

def harvest_blog(config):
    '''Harvest metadata for all blog entries.'''

    all_meta = []
    for folder in glob.glob('blog/????/??'):
        for post in glob.glob('{0}/*.html'.format(folder)):
            m = harvest_metadata(post)
            m['folder'] = folder
            fill_optional_metadata(m, 'favorite')
            all_meta.append(m)

    all_meta.sort(lambda x, y: cmp(x['date'], y['date']) or cmp(x['time'], y['time']))
    return all_meta

#----------------------------------------

def fill_optional_metadata(post, *fields):
    '''
    Fill in metadata fields that are only provided for some posts.
    '''
    for f in fields:
        if f not in post:
            post[f] = None

#----------------------------------------

def check_blog_sanity(posts):
    '''Make sure all blog posts have sensible metadata.'''
    seen = {}
    errors = False
    for p in posts:
        timestamp = (p['date'], p['time'])
        if timestamp in seen:
            print >> sys.stderr, 'Timestamp {0} in {1} duplicated in {2}'.format(timestamp, seen[timestamp], p['path'])
            errors = True
        else:
            seen[timestamp] = p['path']
    if errors:
        sys.exit(1)

#----------------------------------------

def organize_blog_entries(posts):
    '''Organize blog entries by year and month.'''

    blog_lookup = {}
    blog_count = {}
    for p in posts:
        year = '%4d' % p['date'].year
        month = '%02d' % p['date'].month
        if year not in blog_lookup:
            blog_lookup[year] = dict([(m,list()) for m in MONTHS.keys()])
            blog_count[year] = dict([(m,0) for m in MONTHS.keys()])
        blog_lookup[year][month].append(p)
        blog_count[year][month] += 1
    return blog_lookup, blog_count

#----------------------------------------

def get_blog_excerpt(path):
    '''Get excerpt from blog post for inclusion in blog index page.
    Have to turn newlines into spaces so that older versions of Jekyll
    (like the one on the server) won't turn them into single backslashes
    when doing inclusion expansion.'''
    with open(path, 'r') as reader:
        temp = reader.read()
        temp = P_BLOG_EXCERPT.search(temp)
        assert temp, 'Blog post {0} lacks excerpt'.format(path)
        return temp.group(1).replace('\n', ' ')

#----------------------------------------

def write_recent_blog_posts(posts):
    '''Write out recent blog posts for inclusion in blog index page.'''
    with open('_includes/recent_blog_posts.html', 'w') as writer:
        for p in posts:
            print >> writer, RECENT_POST % p

#----------------------------------------

if __name__ == '__main__':
    main()
