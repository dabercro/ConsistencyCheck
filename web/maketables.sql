CREATE TABLE "stats" (site varchar(127) PRIMARY KEY, time float, files int, nodes int, emtpy int, cores int, missing int, m_size int, orphan int, o_size int, entered datetime, nosource int, unlisted INT DEFAULT 0);

CREATE TABLE "stats_history" (site varchar(127), time float, files int, nodes int, emtpy int, cores int, missing int, m_size int, orphan int, o_size int, entered datetime, nosource int, unlisted INT DEFAULT 0, PRIMARY KEY (site, entered));

CREATE TABLE sites (site varchar(64) primary key, isgood int default 0, isrunning INT DEFAULT 0);
