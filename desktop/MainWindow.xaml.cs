using System.Windows;
using System.Windows.Input;
using System.Windows.Media.Animation;
using System.ComponentModel;
using System.Collections.Specialized;
using System.Windows.Media;
using System.Windows.Threading;

namespace JarvisAI;

public partial class MainWindow : Window
{
    private readonly MainViewModel? viewModel;
    private readonly Dictionary<(DependencyObject,DependencyProperty),DispatcherTimer> cleanups=new();
    internal int MotionStarted { get; private set; }
    private bool AllowsMotion => viewModel is { ReduceMotion:false } && SystemParameters.ClientAreaAnimation;
    public MainWindow()
    {
        InitializeComponent();
        viewModel=DataContext as MainViewModel;
        if(viewModel is not null){viewModel.PropertyChanged+=AnimateState;viewModel.Messages.CollectionChanged+=AnimateTranscript;}
        Closed += (_, _) => Release();
    }

    internal void Release()
    {
        if(viewModel is not null){viewModel.PropertyChanged-=AnimateState;viewModel.Messages.CollectionChanged-=AnimateTranscript;viewModel.Dispose();}
        ResetMotion();
    }

    private void Fade(UIElement element,double from=.55) => Run(element,OpacityProperty,from,1,220);
    private void Run(Animatable target,DependencyProperty property,double from,double to,int duration)
    {
        ClearPending(target,property);target.BeginAnimation(property,null);
        if(!AllowsMotion)return;
        MotionStarted++;
        target.BeginAnimation(property,new DoubleAnimation(from,to,TimeSpan.FromMilliseconds(duration)){EasingFunction=new CubicEase{EasingMode=EasingMode.EaseOut},FillBehavior=FillBehavior.Stop},HandoffBehavior.SnapshotAndReplace);
        CleanupAfter(target,property,()=>target.BeginAnimation(property,null),duration);
    }
    private void Run(UIElement target,DependencyProperty property,double from,double to,int duration)
    {
        ClearPending(target,property);target.BeginAnimation(property,null);if(!AllowsMotion)return;MotionStarted++;
        target.BeginAnimation(property,new DoubleAnimation(from,to,TimeSpan.FromMilliseconds(duration)){EasingFunction=new CubicEase{EasingMode=EasingMode.EaseOut},FillBehavior=FillBehavior.Stop},HandoffBehavior.SnapshotAndReplace);
        CleanupAfter(target,property,()=>target.BeginAnimation(property,null),duration);
    }
    private void ClearPending(DependencyObject target,DependencyProperty property)
    {if(cleanups.Remove((target,property),out var timer))timer.Stop();}
    private void CleanupAfter(DependencyObject target,DependencyProperty property,Action clear,int duration)
    {
        var key=(target,property);var timer=new DispatcherTimer(DispatcherPriority.Render){Interval=TimeSpan.FromMilliseconds(duration+32)};
        timer.Tick+=(_,_)=>{timer.Stop();if(cleanups.Remove(key))clear();};cleanups[key]=timer;timer.Start();
    }
    private void Pulse()
    {
        var scale=AllowsMotion&&viewModel?.IsListening==true?1.04:1;
        WelcomeOrbScale.ScaleX=WelcomeOrbScale.ScaleY=scale;
        Run(WelcomeOrbScale,ScaleTransform.ScaleXProperty,.96,scale,360);Run(WelcomeOrbScale,ScaleTransform.ScaleYProperty,.96,scale,360);
        double activityScale=viewModel?.IsBusy==true?1.2:1;ActivityOrbScale.ScaleX=ActivityOrbScale.ScaleY=activityScale;ActivityOrb.Opacity=viewModel?.IsBusy==true||viewModel?.IsListening==true?1:.6;
        Run(ActivityOrbScale,ScaleTransform.ScaleXProperty,.8,activityScale,320);Run(ActivityOrbScale,ScaleTransform.ScaleYProperty,.8,activityScale,320);
    }
    private void AnimateState(object? sender,PropertyChangedEventArgs args)
    {
        if(args.PropertyName==nameof(MainViewModel.ReduceMotion)){ResetMotion();return;}
        if(args.PropertyName==nameof(MainViewModel.Section)){Fade(MainContent);Run(SectionOffset,TranslateTransform.YProperty,8,0,240);}
        if(args.PropertyName==nameof(MainViewModel.ConnectionStatus)){Fade(ActivityStatus,.65);Pulse();}
        if(args.PropertyName is nameof(MainViewModel.IsBusy) or nameof(MainViewModel.IsListening))Pulse();
        if(args.PropertyName==nameof(MainViewModel.AudioLevel)&&viewModel is { IsListening:true })
        {
            var scale=1+Math.Min(viewModel.AudioLevel*2,.12);
            Run(ActivityOrbScale,ScaleTransform.ScaleXProperty,1,scale,100);Run(ActivityOrbScale,ScaleTransform.ScaleYProperty,1,scale,100);
        }
    }
    private void AnimateTranscript(object? sender,NotifyCollectionChangedEventArgs args)
    {if(args.Action==NotifyCollectionChangedAction.Add)Fade(Transcript,.7);}
    private void ResetMotion()
    {
        foreach(var timer in cleanups.Values)timer.Stop();cleanups.Clear();
        MainContent.BeginAnimation(OpacityProperty,null);Transcript.BeginAnimation(OpacityProperty,null);ActivityStatus.BeginAnimation(OpacityProperty,null);
        SectionOffset.BeginAnimation(TranslateTransform.YProperty,null);
        foreach(var scale in new[]{WelcomeOrbScale,ActivityOrbScale}){scale.BeginAnimation(ScaleTransform.ScaleXProperty,null);scale.BeginAnimation(ScaleTransform.ScaleYProperty,null);scale.ScaleX=scale.ScaleY=1;}
    }

    internal async Task<object> VerifyMotionAsync()
    {
        if(viewModel is null)throw new InvalidOperationException("Missing view model");
        bool saved=viewModel.ReduceMotion;viewModel.ReduceMotion=false;int before=MotionStarted;
        viewModel.Section="Memory";await Task.Delay(70);
        bool active=MainContent.HasAnimatedProperties||SectionOffset.HasAnimatedProperties;
        viewModel.IsListening=true;viewModel.AudioLevel=.04;await Task.Delay(50);
        bool orbActive=ActivityOrbScale.HasAnimatedProperties;
        viewModel.ReduceMotion=true;
        bool cancelled=!MainContent.HasAnimatedProperties&&!ActivityOrbScale.HasAnimatedProperties;
        int after=MotionStarted;viewModel.Section="Preferences";viewModel.IsListening=false;viewModel.ConnectionStatus="Reduced motion check";
        bool reducedImmediate=MotionStarted==after&&MainContent.Opacity==1&&SectionOffset.Y==0;
        viewModel.ReduceMotion=false;viewModel.Section="Assistant";await Task.Delay(450);
        // Remove stopped clocks after the finite transition, without holding visual state.
        bool settled=!MainContent.HasAnimatedProperties&&!SectionOffset.HasAnimatedProperties;
        viewModel.ReduceMotion=saved;
        if(SystemParameters.ClientAreaAnimation&&(!active||!orbActive||!cancelled||!reducedImmediate||!settled))throw new InvalidOperationException($"Native motion acceptance failed: active={active}, orbActive={orbActive}, cancelled={cancelled}, reducedImmediate={reducedImmediate}, settled={settled}");
        return new{passed=true,systemAllowsMotion=SystemParameters.ClientAreaAnimation,started=MotionStarted-before,active,orbActive,cancelled,reducedImmediate,settled,syntheticListeningState=true};
    }

    private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ClickCount == 2)
            WindowState = WindowState == WindowState.Maximized
                ? WindowState.Normal : WindowState.Maximized;
        else
            DragMove();
    }

    private void Minimize_Click(object sender, RoutedEventArgs e) =>
        WindowState = WindowState.Minimized;

    private void Close_Click(object sender, RoutedEventArgs e) =>
        Application.Current.Shutdown();

    private void InputBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && !Keyboard.IsKeyDown(Key.LeftShift))
        {
            if (DataContext is MainViewModel vm)
                vm.SendTextCommand.Execute(null);
            e.Handled = true;
        }
    }
}
