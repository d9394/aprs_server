
CREATE TABLE `aprspacket` (
  `tm` timestamp NOT NULL DEFAULT current_timestamp(),
  `call` varchar(16) NOT NULL,
  `datatype` char(1) NOT NULL,
  `lat` char(8) NOT NULL,
  `lon` char(9) NOT NULL,
  `table` char(1) NOT NULL,
  `symbol` char(1) NOT NULL,
  `msg` varchar(200) NOT NULL,
  `raw` varchar(250) NOT NULL,
  KEY `tm` (`tm`),
  KEY `tm_call` (`tm`,`call`),
  KEY `call_tm` (`call`,`tm`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE `aprspackethourcount` (
  `tm` timestamp NOT NULL DEFAULT current_timestamp(),
  `call` varchar(16) NOT NULL,
  `pkts` int(10) DEFAULT NULL,
  PRIMARY KEY (`tm`,`call`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE `lastpacket` (
  `call` varchar(16) NOT NULL,
  `tm` timestamp NOT NULL DEFAULT current_timestamp(),
  `datatype` char(1) NOT NULL,
  `lat` char(8) NOT NULL,
  `lon` char(9) NOT NULL,
  `table` char(1) NOT NULL,
  `symbol` char(1) NOT NULL,
  `msg` varchar(200) NOT NULL,
  `speed` smallint(5) unsigned DEFAULT NULL COMMENT 'Speed in km/h',
  PRIMARY KEY (`call`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE `packetstats` (
  `day` date NOT NULL DEFAULT '0000-00-00',
  `packets` int(10) DEFAULT NULL,
  PRIMARY KEY (`day`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;



