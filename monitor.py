#!/usr/bin/python2

# based on code by henryk ploetz
# https://hackaday.io/project/5301-reverse-engineering-a-low-cost-usb-co-monitor/log/17909-all-your-base-are-belong-to-us

import sys, fcntl, time, rrdtool, os, argparse, socket
from rrdtool import update as rrd_update

RRDDB_LOC = "/var/local/monitor/co2-temp.rrd"
GRAPHOUT_DIR = "/var/www/html/images"

def decrypt(key,  data):
    cstate = [0x48,  0x74,  0x65,  0x6D,  0x70,  0x39,  0x39,  0x65]
    shuffle = [2, 4, 0, 7, 1, 6, 5, 3]
    
    phase1 = [0] * 8
    for i, o in enumerate(shuffle):
        phase1[o] = data[i]
    
    phase2 = [0] * 8
    for i in range(8):
        phase2[i] = phase1[i] ^ key[i]
    
    phase3 = [0] * 8
    for i in range(8):
        phase3[i] = ( (phase2[i] >> 3) | (phase2[ (i-1+8)%8 ] << 5) ) & 0xff
    
    ctmp = [0] * 8
    for i in range(8):
        ctmp[i] = ( (cstate[i] >> 4) | (cstate[i]<<4) ) & 0xff
    
    out = [0] * 8
    for i in range(8):
        out[i] = (0x100 + phase3[i] - ctmp[i]) & 0xff
    
    return out

def hd(d):
    return " ".join("%02X" % e for e in d)

def now():
    return int(time.time())

def graphout(period):
    filename = GRAPHOUT_DIR + "/co2-" + period + "-graph.png" 
    rrdtool.graph(filename,
        "--start", "now-"+period, "--end", "now",
        "--title", "CO2",
        "--vertical-label", "CO2 PPM",
        "--width", "600",
        "-h 200",
        "-l 0",
        "DEF:co2_num="+RRDDB_LOC+":CO2:AVERAGE",
        "LINE1:co2_num#0000FF:CO2",
        "GPRINT:co2_num:LAST: Last\\:%8.2lf %s ",
        "GPRINT:co2_num:MIN: Min\\:%8.2lf %s ",
        "GPRINT:co2_num:AVERAGE: Avg\\:%8.2lf %s ",
        "GPRINT:co2_num:MAX: Max\\:%8.2lf %s\\n",
        "HRULE:500#16F50F:OK",
        "COMMENT: \\n",
        "HRULE:800#FF952B:DEV-WARN",
        "COMMENT: \\n",
        "HRULE:1000#3FC0EB:OFF-WARN",
        "COMMENT: \\n",
        "HRULE:1200#DE2C2F:CRIT")

    filename = GRAPHOUT_DIR + "/temp-" + period + "-graph.png" 
    rrdtool.graph(filename,
        "--start", "now-"+period, "--end", "now",
        "--title", "TEMP",
        "--vertical-label", "TEMP C",
        "--width", "600",
        "-h 200",
        "DEF:temp_num="+RRDDB_LOC+":TEMP:AVERAGE",
        "LINE1:temp_num#00FF00:TEMP",
        "GPRINT:temp_num:LAST: Last\\:%8.2lf %s ",
        "GPRINT:temp_num:MIN: Min\\:%8.2lf %s ",
        "GPRINT:temp_num:AVERAGE: Avg\\:%8.2lf %s ",
        "GPRINT:temp_num:MAX: Max\\:%8.2lf %s \\n")

if __name__ == "__main__":
    # use lock on socket to indicate that script is already running
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        ## Create an abstract socket, by prefixing it with null.
        s.bind('\0postconnect_gateway_notify_lock')
    except socket.error, e:
        # if script is already running just exit silently
        sys.exit(0)
            
    key = [0xc4, 0xc6, 0xc0, 0x92, 0x40, 0x23, 0xdc, 0x96]    
    fp = open(sys.argv[1], "a+b",  0)
    HIDIOCSFEATURE_9 = 0xC0094806
    set_report = "\x00" + "".join(chr(e) for e in key)
    fcntl.ioctl(fp, HIDIOCSFEATURE_9, set_report)
    
    #parser = argparse.ArgumentParser(description='Plot CO2 and TEMP')
    #parser.add_argument('-d', action="store_true", default=False, help="start as deamon")
    #args = parser.parse_args()

    #deamon = False
    #if (args.d):
        #deamon = True

    values = {}
    stamp = now()

    if not os.path.isfile(RRDDB_LOC):
        print "RRD database not found, generating it .."

        # updated every 5 minutes (--step 300)
        # two datasources which can hold unlimit values min and max
        # saves 1 day in 5-minute resolution (288 * (300*1/60) / 60/24)
        # saves 1 week in in 15-minute resolution (672 * (300*3/60) / 60/24)
        # saves 1 month in 1-hour resolution (744 * (300*12/60) / 60/24)
        # saves 7 years in 1-hour resolution
        rddbh = rrdtool.create(RRDDB_LOC, "--step", "300", "--start", '0',
            "DS:CO2:GAUGE:600:U:U",
            "DS:TEMP:GAUGE:600:U:U",
            "RRA:AVERAGE:0.5:1:288",
            "RRA:AVERAGE:0.5:3:672",
            "RRA:AVERAGE:0.5:12:744",
            "RRA:AVERAGE:0.5:12:61320",
            "RRA:MIN:0.5:1:288",
            "RRA:MIN:0.5:3:672",
            "RRA:MIN:0.5:12:744",
            "RRA:MIN:0.5:12:61320",
            "RRA:MAX:0.5:1:288",
            "RRA:MAX:0.5:3:672",
            "RRA:MAX:0.5:12:744",
            "RRA:MAX:0.5:12:61320")

    while True:
        data = list(ord(e) for e in fp.read(8))
        decrypted = decrypt(key, data)
        if decrypted[4] != 0x0d or (sum(decrypted[:3]) & 0xff) != decrypted[3]:
            print hd(data), " => ", hd(decrypted),  "Checksum error"
        else:
            op = decrypted[0]
            val = decrypted[1] << 8 | decrypted[2]
            values[op] = val

            if (0x50 in values) and (0x42 in values):
                co2 = values[0x50]
                tmp = (values[0x42]/16.0-273.15)

                sys.stdout.write("CO2: %4i TMP: %3.1f    \r" % (co2, tmp))
                sys.stdout.flush()
            
                if now() - stamp > 60:
                    print ">>> sending dataset CO2: %4i TMP: %3.1f .." % (co2, tmp)
                    rrd_update(RRDDB_LOC, 'N:%s:%s' % (co2, tmp))
                    graphout("8h")
                    graphout("24h")
                    graphout("7d")
                    graphout("1m")
                    graphout("1y")
                    stamp = now()
