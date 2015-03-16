# youtube2mediawiki

youtube2mediawiki is a command line tool, that allows you to download WebM videos from Youtube and import them into Mediawiki.

## Usage 

```youtube2mediawiki.py [options] youtubeid```

### Options

option                            | description
--------------------------------- | --------------------------------------------------------------------------
-h, --help                        | show this help message and exit
-u USERNAME, --username=USERNAME  | wiki username
-p PASSWORD, --password=PASSWORD  | wiki password (can also be provided via Y2M_PASSWORD environment vairable)
-w URL, --url=URL                 | wiki api url
-n NAME, --name=NAME              | name of file on wiki, by default title on youtube is used
-d, --debug                       | output debug information
-i, --ignore-warnings             | ignore warnings during upload
-a, --adaptive-streaming          | fetch HD VP9 stream + audio stream and merge both using ffmpeg
-o, --overwrite                   | force overwriting files at the destination wiki (requires --ignore-warnings)

## Notes

- If you run this on a shared server, you should not pass your password as an
  argument as it is visible via ps ax. Instead you can set an environment
  variable:
    export Y2M_PASSWORD=yourpassword
    youtube2mediawiki.py -u .

- A small number of Videos does not have a WebM version created by youtube. For
  newly uploaded videos it takes usually some hours until the WebM transcodes
  are publicly available. Additionally Videos have to be set to "unlisted" or
  "public" available.

- Some YouTube Video IDs start with a hyphen. You can also pass a url like
  http://www.youtube.com/watch?v=YouTubeId or prepend a double hypen (--) to the
  YouTube ID to ensure youtube2mediawiki accepts them.

- Some names are not accepted on wiki projects and you may choose a more
  appropriate name using the NAME option (-n NAME.webm).
