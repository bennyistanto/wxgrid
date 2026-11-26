# Export tables of an Access .mdb to UTF-8 CSV, read-only, via the 64-bit Access ODBC driver.
# Python's pyodbc is not installed in this environment; PowerShell's System.Data.Odbc is.
#
# Usage:
#   pwsh tools/export_mdb.ps1 -Mdb F:\temp\station\asean-compendium\Daily.mdb `
#        -Out F:\temp\station\asean-compendium\export `
#        -Tables tbl_country,tbl_Element,tbl_Period,tbl_station_info,tbl_Rainfall,tbl_Temperature
param(
    [Parameter(Mandatory)] [string] $Mdb,
    [Parameter(Mandatory)] [string] $Out,
    [Parameter(Mandatory)] [string[]] $Tables
)
New-Item -ItemType Directory -Force $Out | Out-Null
$cs = "Driver={Microsoft Access Driver (*.mdb, *.accdb)};Dbq=$Mdb;ReadOnly=1;"
$c = New-Object System.Data.Odbc.OdbcConnection($cs)
$c.Open()
try {
    foreach ($n in $Tables) {
        $cmd = $c.CreateCommand()
        $cmd.CommandText = "SELECT * FROM [$n]"
        $r = $cmd.ExecuteReader()
        $w = New-Object System.IO.StreamWriter("$Out\$n.csv", $false, [System.Text.UTF8Encoding]::new($false))
        $names = 0..($r.FieldCount - 1) | ForEach-Object { $r.GetName($_) }
        $w.WriteLine(($names -join ','))
        $vals = New-Object object[] $r.FieldCount
        $k = 0
        while ($r.Read()) {
            [void]$r.GetValues($vals)
            $w.WriteLine((($vals | ForEach-Object { '"' + ([string]$_).Replace('"', '""') + '"' }) -join ','))
            $k++
        }
        $w.Close(); $r.Close()
        "$n -> $k rows"
    }
}
finally { $c.Close() }
