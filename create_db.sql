CREATE TABLE `lastpacket` (
  `call` varchar(16) NOT NULL,
  `tm` timestamp NOT NULL DEFAULT current_timestamp(),
  `datatype` char(1) NOT NULL,
  `lat` char(8) NOT NULL,
  `lon` char(9) NOT NULL,
  `table` char(1) NOT NULL,
  `symbol` char(1) NOT NULL,
  `msg` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `speed` int(6) DEFAULT 0,
  PRIMARY KEY (`call`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

CREATE TABLE `aprspacket` (
  `tm` timestamp NOT NULL DEFAULT current_timestamp(),
  `call` varchar(16) NOT NULL,
  `datatype` char(1) NOT NULL,
  `lat` char(8) NOT NULL,
  `lon` char(9) NOT NULL,
  `table` char(1) NOT NULL,
  `symbol` char(1) NOT NULL,
  `msg` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `raw` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  KEY `tm` (`tm`),
  KEY `tm_call` (`tm`,`call`),
  KEY `call_tm` (`call`,`tm`),
  KEY `tm_lat` (`tm`,`lat`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

CREATE TABLE `aprspackethourcount` (
  `tm` timestamp NOT NULL DEFAULT current_timestamp(),
  `call` varchar(16) NOT NULL,
  `pkts` int(10) DEFAULT NULL,
  PRIMARY KEY (`tm`,`call`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

CREATE TABLE `packetstats` (
  `day` date NOT NULL DEFAULT '0000-00-00',
  `packets` int(10) DEFAULT NULL,
  PRIMARY KEY (`day`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;
