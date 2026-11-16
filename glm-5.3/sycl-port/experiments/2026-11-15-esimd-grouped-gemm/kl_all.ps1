$X='<work>\experiments\claude-glm-l12-20261115'
$live='<work>\rt-glm-q6al-20261114\generate.exe'; $cand="$X\tree\link\generate.exe"
foreach ($case in 'long32k','code') {
  foreach ($a in @(@('live',$live,''),@('esimd',$cand,'1'),@('joint',$cand,'0'),@('live2',$live,''))) {
    try { $r = & "$X\kl_l12.ps1" -Case $case -Exe $a[1] -Esimd $a[2] -Tag $a[0] } catch { $r = "$case-$($a[0]) FAILED $($_.Exception.Message)" }
    $r
    if ($r -notmatch 'EXIT 0') { 'STOPPED'; exit 1 }
  }
}
'KL_DONE'
